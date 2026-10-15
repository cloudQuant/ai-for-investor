"""Versioned composition metadata and source-aware read projections."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.service_read import _resolve_access
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.auth import TokenPayload
from app.schemas.portfolio_composition import PortfolioCompositionCreate
from app.services.service_read.client import ServiceReadUnavailableError
from app.services.service_read.contracts import AccountReadView, ReadQuality


class PortfolioCompositionService:
    """Own append-only memberships and project facts from their source owner."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_version(
        self, owner_subject: str, request: PortfolioCompositionCreate
    ) -> PortfolioCompositionVersion:
        """Persist a new membership version without rewriting earlier versions."""

        canonical_members = sorted(
            (member.model_dump(mode="json") for member in request.members),
            key=lambda member: (member["kind"], member["ref"]),
        )
        membership_document = {
            "source_type": request.source_type,
            "base_currency": request.base_currency,
            "members": canonical_members,
        }
        membership_sha256 = hashlib.sha256(
            json.dumps(
                membership_document,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        latest = await self.db.scalar(
            select(func.max(PortfolioCompositionVersion.membership_version)).where(
                PortfolioCompositionVersion.owner_subject == owner_subject,
                PortfolioCompositionVersion.portfolio_ref == request.portfolio_ref,
            )
        )
        row = PortfolioCompositionVersion(
            owner_subject=owner_subject,
            portfolio_ref=request.portfolio_ref,
            membership_version=(latest or 0) + 1,
            source_type=request.source_type,
            base_currency=request.base_currency,
            members=canonical_members,
            membership_sha256=membership_sha256,
        )
        self.db.add(row)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "MEMBERSHIP_VERSION_CONFLICT"},
            ) from None
        await self.db.refresh(row)
        return row

    async def get_version(
        self, owner_subject: str, portfolio_ref: str, membership_version: int
    ) -> PortfolioCompositionVersion:
        """Read one exact version owned by the authenticated subject."""

        row = await self.db.scalar(
            select(PortfolioCompositionVersion).where(
                PortfolioCompositionVersion.owner_subject == owner_subject,
                PortfolioCompositionVersion.portfolio_ref == portfolio_ref,
                PortfolioCompositionVersion.membership_version == membership_version,
            )
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "PORTFOLIO_COMPOSITION_NOT_FOUND"},
            )
        return row

    async def list_versions(
        self, owner_subject: str, page: int, page_size: int
    ) -> tuple[list[PortfolioCompositionVersion], int]:
        """Return only this owner's version metadata in stable paginated order."""

        owner_filter = PortfolioCompositionVersion.owner_subject == owner_subject
        result = await self.db.execute(
            select(PortfolioCompositionVersion, func.count().over())
            .where(owner_filter)
            .order_by(
                PortfolioCompositionVersion.portfolio_ref.asc(),
                PortfolioCompositionVersion.membership_version.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = result.all()
        if rows:
            return [row[0] for row in rows], int(rows[0][1])

        # An out-of-range page has no row carrying the window count.
        total = await self.db.scalar(
            select(func.count()).select_from(PortfolioCompositionVersion).where(owner_filter)
        )
        return [], int(total or 0)

    async def project(
        self, current_user: TokenPayload, row: PortfolioCompositionVersion
    ) -> dict[str, Any]:
        """Project only facts available from the membership's exact source."""

        base = {
            "portfolio_ref": row.portfolio_ref,
            "membership_version": row.membership_version,
            "membership_sha256": row.membership_sha256,
            "source_type": row.source_type,
            "base_currency": row.base_currency,
            "members": list(row.members),
            "projection_kind": "display_only",
            "creditable": False,
            "overlap_policy": "non_additive_display_only",
        }
        if row.source_type != "live":
            return {
                **base,
                "source_status": "adapter_not_integrated",
                "account_total": {
                    "status": "not_collected",
                    "currency": row.base_currency,
                    "value": None,
                },
                "accounts": [],
                "strategies": _strategy_views(row.members),
                "strategy_attribution": _unavailable_attribution(
                    None, sum(member["kind"] == "strategy" for member in row.members)
                ),
                "coverage": {
                    "complete": False,
                    "code": f"{row.source_type.upper()}_FACT_ADAPTER_NOT_INTEGRATED",
                },
            }

        account_members = [member for member in row.members if member["kind"] == "account"]
        reads: list[tuple[str, AccountReadView | None, str | None]] = []
        for member in account_members:
            try:
                access = _resolve_access(current_user, member["ref"], "account")
            except HTTPException:
                raise
            try:
                view = await access.worker.read_account(member["ref"], currency=row.base_currency)
            except ServiceReadUnavailableError as error:
                if error.code in {
                    "CAPABILITY_UNAVAILABLE",
                    "DENIED",
                    "DUPLICATE_ACTIVE_RUN",
                    "NOT_REGISTERED",
                    "POLICY_REQUIREMENT_UNMET",
                    "SCOPE_DENIED",
                    "STALE_EPOCH",
                    "ACCOUNT_NOT_CONFIGURED",
                    "SCOPE_NOT_CONFIGURED",
                }:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={"code": "SERVICE_READ_ACCESS_DENIED"},
                    ) from None
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "SERVICE_READ_FAILED"},
                ) from None
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "SERVICE_READ_FAILED"},
                ) from None
            if type(view) is not AccountReadView:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "SERVICE_READ_CONTRACT_INVALID"},
                )
            if view.account_ref != member["ref"]:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "SERVICE_READ_CONTRACT_INVALID"},
                )
            identity = _verified_account_key_id(view)
            reads.append((member["ref"], view, identity))

        account_rows, account_total = _project_account_total(reads, row.base_currency)
        account_facts_complete = account_total["status"] == "current"
        strategy_count = sum(member["kind"] == "strategy" for member in row.members)
        attribution_complete = strategy_count == 0
        if not account_facts_complete:
            coverage_code = "ACCOUNT_FACT_COVERAGE_INCOMPLETE"
        elif not attribution_complete:
            coverage_code = "EXECUTION_ATTRIBUTION_NOT_COLLECTED"
        else:
            coverage_code = None
        return {
            **base,
            "source_status": "projected" if account_members else "no_account_members",
            "accounts": account_rows,
            "strategies": _strategy_views(row.members),
            "account_total": account_total,
            "strategy_attribution": _unavailable_attribution(
                account_total["value"] if account_facts_complete else None,
                strategy_count,
            ),
            "coverage": {
                "complete": account_facts_complete and attribution_complete,
                "account_facts_complete": account_facts_complete,
                "strategy_attribution_complete": attribution_complete,
                "code": coverage_code,
            },
        }


def _project_account_total(
    reads: list[tuple[str, AccountReadView | None, str | None]], currency: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[tuple[str, AccountReadView]]] = defaultdict(list)
    unresolved: list[tuple[str, AccountReadView]] = []
    for member_ref, view, identity in reads:
        assert view is not None
        if not identity:
            unresolved.append((member_ref, view))
        else:
            grouped[identity].append((member_ref, view))

    rows: list[dict[str, Any]] = []
    total = Decimal("0")
    complete = not unresolved
    by_identity: dict[str, tuple[str, AccountReadView, bool]] = {}
    for identity, entries in grouped.items():
        distinct_values = {(entry.value, entry.cash, entry.currency) for _, entry in entries}
        conflict = len(distinct_values) > 1
        best_ref, best_view = min(
            entries,
            key=lambda item: (
                0 if item[1].quality is ReadQuality.FRESH else 1,
                item[1].received_age_seconds
                if item[1].received_age_seconds is not None
                else float("inf"),
                item[0],
            ),
        )
        included = (
            not conflict
            and best_view.quality is ReadQuality.FRESH
            and best_view.currency == currency
            and best_view.value is not None
        )
        by_identity[identity] = (best_ref, best_view, included)
        if included:
            total += best_view.value
        else:
            complete = False
        if conflict:
            complete = False

    for member_ref, view in unresolved:
        rows.append(_account_row(member_ref, view, False, None, "ACCOUNT_IDENTITY_MISSING"))
    for identity, entries in grouped.items():
        primary_ref, _, included = by_identity[identity]
        for member_ref, view in entries:
            duplicate_of = None if member_ref == primary_ref else primary_ref
            conflict = len({(entry.value, entry.cash, entry.currency) for _, entry in entries}) > 1
            rows.append(
                _account_row(
                    member_ref,
                    view,
                    included and member_ref == primary_ref,
                    duplicate_of,
                    "DUPLICATE_ACCOUNT_FACT_CONFLICT" if conflict else view.detail_code,
                )
            )

    rows.sort(key=lambda item: item["member_ref"])
    if not reads:
        status_value = "not_collected"
        projected_total: str | None = None
    elif complete:
        status_value = "current"
        projected_total = format(total, "f")
    else:
        status_value = "incomplete"
        projected_total = None
    return rows, {"status": status_value, "currency": currency, "value": projected_total}


def _account_row(
    member_ref: str,
    view: AccountReadView,
    included: bool,
    duplicate_of: str | None,
    detail_code: str | None,
) -> dict[str, Any]:
    return {
        "member_ref": member_ref,
        "currency": view.currency,
        "quality": view.quality.value,
        "cash": _decimal_text(view.cash),
        "value": _decimal_text(view.value),
        "observed_at_utc": view.observed_at_utc,
        "included_in_total": included,
        "duplicate_of_ref": duplicate_of,
        "detail_code": detail_code,
    }


def _verified_account_key_id(view: AccountReadView) -> str | None:
    """Recompute identity with the base SDK type before using a key for dedupe."""

    if view.account_key is None or view.account_key_id is None:
        return None
    try:
        from bt_api_base.account_protocol import AccountKey

        key = AccountKey.from_dict(dict(view.account_key))
    except (ImportError, TypeError, ValueError):
        return None
    return key.account_key_id if key.account_key_id == view.account_key_id else None


def _unavailable_attribution(
    unattributed_account_value: str | None, strategy_count: int
) -> dict[str, Any]:
    return {
        "status": "execution_attribution_not_collected",
        "strategy_count": strategy_count,
        "attributed_value": None,
        "unattributed_account_value": unattributed_account_value,
        "residual_basis": "account total only; no strategy shares inferred",
    }


def _strategy_views(members: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "strategy_ref": member["ref"],
            "attribution_status": "execution_attribution_not_collected",
            "attributed_value": None,
        }
        for member in members
        if member["kind"] == "strategy"
    ]


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
