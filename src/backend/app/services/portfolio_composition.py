"""Versioned composition metadata and source-aware read projections."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.service_read import _resolve_access
from app.models.asset_research import AssetAnalysisReport, AssetAnalysisTask
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.models.portfolio_ledger import PortfolioLedgerImportModel, PortfolioLedgerModel
from app.schemas.auth import TokenPayload
from app.schemas.portfolio_composition import PortfolioCompositionCreate
from app.services.asset_research.data import canonical_json_hash
from app.services.portfolio_import_source import verify_portfolio_import_source
from app.services.service_read.client import ServiceReadUnavailableError
from app.services.service_read.contracts import (
    AccountBookReadView,
    AccountReadView,
    ReadQuality,
)


class PortfolioCompositionService:
    """Own append-only memberships and project facts from their source owner."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_version(
        self, owner_subject: str, request: PortfolioCompositionCreate
    ) -> PortfolioCompositionVersion:
        """Persist a new membership version without rewriting earlier versions."""

        from app.services.strategy_approval_authority import (
            advance_strategy_approval_authority_epoch,
            lock_strategy_approval_authority_epoch,
        )

        try:
            await lock_strategy_approval_authority_epoch(self.db, owner_subject)

            if request.source_type == "imported":
                imported_refs = [member.ref for member in request.members]
                owned_result = await self.db.execute(
                    select(PortfolioLedgerImportModel.id)
                    .join(
                        PortfolioLedgerModel,
                        PortfolioLedgerModel.id == PortfolioLedgerImportModel.portfolio_id,
                    )
                    .where(
                        PortfolioLedgerImportModel.id.in_(imported_refs),
                        PortfolioLedgerModel.owner_id == owner_subject,
                    )
                )
                if set(owned_result.scalars().all()) != set(imported_refs):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail={"code": "PORTFOLIO_IMPORT_SOURCE_NOT_FOUND"},
                    )

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
            await advance_strategy_approval_authority_epoch(self.db, owner_subject)
            await self.db.commit()
            await self.db.refresh(row)
            return row
        except BaseException as error:
            try:
                await self.db.rollback()
            except BaseException as rollback_error:
                raise error from rollback_error
            if isinstance(error, IntegrityError):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "MEMBERSHIP_VERSION_CONFLICT"},
                ) from None
            raise

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
        if row.source_type == "research":
            return await self._project_research_source(current_user, row, base)
        if row.source_type == "imported":
            return await self._project_imported_source(current_user, row, base)
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

        return await self._project_live_source(current_user, row, base)

    async def _project_live_source(
        self,
        current_user: TokenPayload,
        row: PortfolioCompositionVersion,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """Project provider totals separately from trusted execution owner books."""

        account_members = [member for member in row.members if member["kind"] == "account"]
        selected_account_refs = {member["ref"] for member in account_members}
        account_access_by_ref = {
            member["ref"]: _resolve_access(current_user, member["ref"], "account_member")
            for member in account_members
        }
        subject_access = next(iter(account_access_by_ref.values()), None)
        reads: list[tuple[str, AccountReadView | None, str | None]] = []
        for member in account_members:
            account_ref = member["ref"]
            access = account_access_by_ref[account_ref]
            if account_ref not in access.allow_account_refs:
                continue
            try:
                view = await access.worker.read_account(account_ref, currency=row.base_currency)
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
            if type(view) is not AccountReadView or view.account_ref != account_ref:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "SERVICE_READ_CONTRACT_INVALID"},
                )
            reads.append((account_ref, view, _verified_account_key_id(view)))

        account_rows, account_total, account_snapshot_consistency = _project_account_total(
            reads, row.base_currency
        )
        provider_snapshot_consistency = _provider_snapshot_consistency(reads)
        account_facts_complete = account_total["status"] == "current"
        strategy_members = [member for member in row.members if member["kind"] == "strategy"]
        strategy_rows = _strategy_views(row.members)
        strategy_row_by_ref = {item["strategy_ref"]: item for item in strategy_rows}
        book_views: dict[str, AccountBookReadView] = {}
        book_sources: dict[str, dict[str, Any]] = {}
        complete_strategy_refs: set[str] = set()
        mapped_strategy_count = 0

        for member in strategy_members:
            strategy_ref = member["ref"]
            strategy_row = strategy_row_by_ref[strategy_ref]
            binding = (
                subject_access.strategy_book_bindings.get(strategy_ref)
                if subject_access is not None
                else None
            )
            if binding is None:
                # Older deployments may not yet map this display selector to
                # an execution owner. Keep it explicitly uncollected.
                continue
            mapped_strategy_count += 1
            account_ref = binding.account_ref
            if account_ref not in selected_account_refs:
                strategy_row.update(
                    {
                        "attribution_status": "account_member_not_selected",
                        "account_ref": account_ref,
                        "positions": None,
                        "fees_since_baseline": None,
                    }
                )
                continue

            access = account_access_by_ref[account_ref]
            if account_ref not in access.allow_account_book_refs:
                strategy_row.update(
                    {
                        "attribution_status": "account_book_not_granted",
                        "account_ref": account_ref,
                        "positions": None,
                        "fees_since_baseline": None,
                    }
                )
                continue

            view = book_views.get(account_ref)
            if view is None:
                try:
                    view = await access.worker.read_account_book(account_ref)
                except ServiceReadUnavailableError as error:
                    if error.code in {
                        "CAPABILITY_UNAVAILABLE",
                        "DENIED",
                        "DUPLICATE_ACTIVE_RUN",
                        "NOT_REGISTERED",
                        "POLICY_REQUIREMENT_UNMET",
                        "SCOPE_DENIED",
                        "STALE_EPOCH",
                        "ACCOUNT_BOOK_NOT_CONFIGURED",
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
                if type(view) is not AccountBookReadView or view.account_ref != account_ref:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail={"code": "SERVICE_READ_CONTRACT_INVALID"},
                    )
                book_views[account_ref] = view

                source = view.to_dict()
                coverage = source["coverage"]
                coverage.pop("account_key", None)
                unallocated_book = next(
                    (
                        item
                        for item in source["books"]
                        if item["owner_kind"] == "UNALLOCATED"
                        and item["owner_ref"] == "UNALLOCATED"
                    ),
                    None,
                )
                book_sources[view.account_key_id] = {
                    "account_ref": account_ref,
                    "state": source["state"],
                    "coverage": coverage,
                    "provider_position_change": source["provider_position_change"],
                    # Preserve the SDK's current unallocated owner book separately
                    # from its baseline-relative position residual below.
                    "unallocated_book": unallocated_book,
                    "position_residual": source["position_residual"],
                    "fee_residual": source["fee_residual"],
                    "financial": _public_financial_projection(source),
                }

            source = view.to_dict()
            source["coverage"].pop("account_key", None)
            owner_book = next(
                (
                    item
                    for item in source["books"]
                    if item["owner_kind"] == "STRATEGY" and item["owner_ref"] == binding.owner_ref
                ),
                None,
            )
            if owner_book is None:
                strategy_row.update(
                    {
                        "attribution_status": "owner_not_in_directory",
                        "account_ref": account_ref,
                        "source_cursor": source["coverage"]["current_execution_cursor"],
                        "positions": None,
                        "fees_since_baseline": None,
                    }
                )
                continue

            source_complete = (
                source["coverage"]["complete"] is True and source["state"] == "BALANCED"
            )
            if source_complete:
                complete_strategy_refs.add(strategy_ref)
            strategy_row.update(
                {
                    "attribution_status": (
                        "available" if source_complete else "available_with_residuals"
                    ),
                    "account_ref": account_ref,
                    "source_cursor": source["coverage"]["current_execution_cursor"],
                    "source_state": source["state"],
                    "positions": owner_book["current_positions"],
                    "fees_since_baseline": owner_book["fees_since_baseline"],
                    "attributed_value": None,
                }
            )

        strategy_count = len(strategy_members)
        attribution_complete = strategy_count == 0 or (
            mapped_strategy_count == strategy_count
            and complete_strategy_refs == {member["ref"] for member in strategy_members}
        )
        if mapped_strategy_count == 0:
            attribution = _unavailable_attribution(
                account_total["value"] if account_facts_complete else None,
                strategy_count,
            )
            coverage_code = (
                "ACCOUNT_FACT_COVERAGE_INCOMPLETE"
                if not account_facts_complete
                else "EXECUTION_ATTRIBUTION_NOT_COLLECTED"
                if strategy_count
                else None
            )
        else:
            attribution = {
                "status": (
                    "execution_account_books_current"
                    if attribution_complete
                    else "execution_account_books_partial"
                ),
                "strategy_count": strategy_count,
                "mapped_strategy_count": mapped_strategy_count,
                "attributed_value": None,
                "unattributed_account_value": None,
                "residual_basis": (
                    "Execution owner-book positions and fees only; "
                    "cash, account value, and FX are not calculated"
                ),
            }
            if not account_facts_complete and not attribution_complete:
                coverage_code = "ACCOUNT_AND_EXECUTION_COVERAGE_INCOMPLETE"
            elif not account_facts_complete:
                coverage_code = "ACCOUNT_FACT_COVERAGE_INCOMPLETE"
            elif not attribution_complete:
                coverage_code = "EXECUTION_ACCOUNT_BOOK_COVERAGE_INCOMPLETE"
            else:
                coverage_code = None
        return {
            **base,
            "source_status": "projected" if account_members else "no_account_members",
            "accounts": account_rows,
            "account_snapshot_consistency": account_snapshot_consistency,
            "provider_snapshot_consistency": provider_snapshot_consistency,
            "strategies": strategy_rows,
            "account_book_sources": list(book_sources.values()),
            "account_total": account_total,
            "strategy_attribution": attribution,
            "coverage": {
                "complete": account_facts_complete and attribution_complete,
                "account_facts_complete": account_facts_complete,
                "strategy_attribution_complete": attribution_complete,
                "code": coverage_code,
            },
        }

    async def _project_imported_source(
        self,
        current_user: TokenPayload,
        row: PortfolioCompositionVersion,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """Project owner-held import source documents without deriving valuations."""

        if not row.members or any(member["kind"] != "imported_ledger" for member in row.members):
            return _unavailable_imported_projection(base, "IMPORTED_SOURCE_MEMBERS_INVALID")

        member_refs = [member["ref"] for member in row.members]
        result = await self.db.execute(
            select(PortfolioLedgerImportModel, PortfolioLedgerModel)
            .join(
                PortfolioLedgerModel,
                PortfolioLedgerModel.id == PortfolioLedgerImportModel.portfolio_id,
            )
            .where(
                PortfolioLedgerImportModel.id.in_(member_refs),
                PortfolioLedgerModel.owner_id == current_user.sub,
            )
        )
        owned_sources = {imported.id: (imported, portfolio) for imported, portfolio in result.all()}
        artifacts: list[dict[str, Any]] = []
        for member_ref in member_refs:
            owned = owned_sources.get(member_ref)
            if owned is None:
                artifacts.append(_unavailable_import_artifact("missing_or_not_owned"))
                continue

            imported, portfolio = owned
            if imported.source_document is None or imported.source_sha256 is None:
                artifacts.append(_unavailable_import_artifact("source_material_unavailable"))
                continue
            if not verify_portfolio_import_source(
                document=imported.source_document,
                expected_sha256=imported.source_sha256,
                expected_schema_version=imported.source_schema_version,
                import_format=imported.import_format,
                imported_count=imported.imported_count,
                source_as_of=imported.source_as_of,
                source_currency=imported.source_currency,
            ):
                artifacts.append(_unavailable_import_artifact("integrity_invalid"))
                continue

            source_rows = imported.source_document["transactions"]
            dates_present = sum(
                1 for source_row in source_rows if _has_explicit_trade_date(source_row)
            )
            if not source_rows:
                date_coverage = "not_applicable_empty_source"
            elif dates_present == len(source_rows):
                date_coverage = "complete"
            elif dates_present == 0:
                date_coverage = "missing"
            else:
                date_coverage = "partial"
            metadata_complete = bool(imported.source_as_of and imported.source_currency)
            artifacts.append(
                {
                    "status": "available",
                    "import_version_id": imported.id,
                    "portfolio_name": portfolio.name,
                    "import_format": imported.import_format,
                    "source_schema_version": imported.source_schema_version,
                    "source_sha256": imported.source_sha256,
                    "source_as_of": imported.source_as_of,
                    "source_as_of_status": (
                        "declared" if imported.source_as_of else "not_declared"
                    ),
                    "source_currency": imported.source_currency,
                    "source_integrity_status": "verified",
                    "currency_status": ("declared" if imported.source_currency else "not_declared"),
                    "freshness_status": "not_defined",
                    "source_row_count": len(source_rows),
                    "trade_date_rows_present": dates_present,
                    "trade_date_coverage": date_coverage,
                    "source_metadata_status": "complete" if metadata_complete else "incomplete",
                    "source_rows_available": True,
                }
            )

        statuses = [artifact["status"] for artifact in artifacts]
        if any(value == "integrity_invalid" for value in statuses):
            coverage_code = "IMPORTED_SOURCE_INTEGRITY_INVALID"
        elif any(value != "available" for value in statuses):
            coverage_code = "IMPORTED_SOURCE_MATERIAL_UNAVAILABLE"
        elif any(artifact["source_metadata_status"] != "complete" for artifact in artifacts):
            coverage_code = "IMPORTED_SOURCE_METADATA_INCOMPLETE"
        elif any(
            artifact["trade_date_coverage"] not in {"complete", "not_applicable_empty_source"}
            for artifact in artifacts
        ):
            coverage_code = "IMPORTED_SOURCE_TRADE_DATES_INCOMPLETE"
        else:
            coverage_code = "IMPORTED_SOURCE_NOT_ACCOUNT_FACTS"

        all_sources_verified = bool(artifacts) and all(value == "available" for value in statuses)
        if all_sources_verified:
            source_status = "imported_materials_projected"
        elif any(value == "integrity_invalid" for value in statuses):
            source_status = "imported_material_integrity_invalid"
        else:
            source_status = "imported_materials_unavailable"
        return {
            **base,
            "source_status": source_status,
            "source_facts": {
                "kind": "portfolio_ledger_import_versions",
                "artifacts": artifacts,
                "source_materials_verified": all_sources_verified,
                "freshness_status": "not_defined",
                "account_value_status": "not_applicable_imported",
            },
            "account_total": {
                "status": "not_applicable_imported",
                "currency": None,
                "value": None,
            },
            "accounts": [],
            "strategies": [],
            "strategy_attribution": _imported_attribution(),
            "coverage": {
                "complete": False,
                "account_facts_complete": False,
                "source_materials_verified": all_sources_verified,
                "code": coverage_code,
            },
        }

    async def _project_research_source(
        self,
        current_user: TokenPayload,
        row: PortfolioCompositionVersion,
        base: dict[str, Any],
    ) -> dict[str, Any]:
        """Read owner-scoped published research reports without treating them as holdings."""

        if not row.members or any(member["kind"] != "research_artifact" for member in row.members):
            return {
                **base,
                "source_status": "adapter_not_integrated",
                "account_total": {
                    "status": "not_applicable_research",
                    "currency": None,
                    "value": None,
                },
                "accounts": [],
                "strategies": [],
                "strategy_attribution": _research_attribution(),
                "coverage": {
                    "complete": False,
                    "code": "RESEARCH_REPORT_ADAPTER_NOT_INTEGRATED",
                },
            }

        member_refs = [member["ref"] for member in row.members]
        result = await self.db.execute(
            select(AssetAnalysisReport, AssetAnalysisTask)
            .join(AssetAnalysisTask, AssetAnalysisTask.id == AssetAnalysisReport.task_id)
            .where(
                AssetAnalysisReport.id.in_(member_refs),
                AssetAnalysisReport.tombstoned_at.is_(None),
                AssetAnalysisTask.owner_scope == "USER",
                AssetAnalysisTask.user_id == current_user.sub,
                AssetAnalysisTask.tombstoned_at.is_(None),
            )
        )
        owned_reports = {report.id: (report, task) for report, task in result.all()}
        source_artifacts: list[dict[str, Any]] = []
        for member_ref in member_refs:
            owned = owned_reports.get(member_ref)
            if owned is None:
                source_artifacts.append(
                    {
                        "status": "missing_or_not_owned",
                        "report_integrity_status": "unavailable",
                        "task_status": None,
                        "asset_type": None,
                        "canonical_id": None,
                        "report_version": None,
                        "report_content_hash": None,
                        "report_created_at": None,
                        "decision_status": "unavailable",
                        "published_decision": None,
                        "freshness_status": "not_defined",
                        "currency": None,
                        "currency_status": "not_declared",
                        "account_value_status": "not_applicable_research",
                    }
                )
                continue

            try:
                report, task = owned
                report_sections = report.sections_json
                if not isinstance(report_sections, dict):
                    raise ValueError("report payload is invalid")
                if canonical_json_hash(report_sections) != report.content_hash:
                    raise ValueError("report content hash mismatch")
                report_meta = report_sections.get("meta")
                if (
                    not isinstance(report_meta, dict)
                    or report_meta.get("asset_type") != task.asset_type
                    or report_meta.get("canonical_id") != task.canonical_id
                ):
                    raise ValueError("report identity mismatch")
                report_created_at = _iso_utc(report.created_at)
            except (AttributeError, TypeError, ValueError):
                # Integrity problems are projected as finite status, never raw content/errors.
                source_artifacts.append(
                    {
                        "status": "integrity_invalid",
                        "report_integrity_status": "invalid",
                        "task_status": None,
                        "asset_type": None,
                        "canonical_id": None,
                        "report_version": None,
                        "report_content_hash": None,
                        "report_created_at": None,
                        "decision_status": "unavailable",
                        "published_decision": None,
                        "freshness_status": "not_defined",
                        "currency": None,
                        "currency_status": "not_declared",
                        "account_value_status": "not_applicable_research",
                    }
                )
                continue

            decision = _published_research_decision(report_sections)
            source_artifacts.append(
                {
                    "status": "available",
                    "report_integrity_status": "verified",
                    "task_status": str(task.status),
                    "asset_type": str(task.asset_type),
                    "canonical_id": str(task.canonical_id),
                    "report_version": str(report.report_version),
                    "report_content_hash": str(report.content_hash),
                    "report_created_at": report_created_at,
                    "decision_status": "available" if decision is not None else "unavailable",
                    "published_decision": decision,
                    # Research reports do not declare a universal freshness SLA or account value.
                    "freshness_status": "not_defined",
                    "currency": None,
                    "currency_status": "not_declared",
                    "account_value_status": "not_applicable_research",
                }
            )

        statuses = [item["status"] for item in source_artifacts]
        if any(value == "missing_or_not_owned" for value in statuses):
            coverage_code = "RESEARCH_REPORT_MISSING_OR_NOT_OWNED"
        elif any(value == "integrity_invalid" for value in statuses):
            coverage_code = "RESEARCH_REPORT_INTEGRITY_INVALID"
        else:
            coverage_code = "RESEARCH_REPORTS_NOT_FINANCIAL_ACCOUNTS"

        all_artifacts_readable = all(value == "available" for value in statuses)
        return {
            **base,
            "source_status": (
                "research_reports_projected"
                if any(value == "available" for value in statuses)
                else "research_reports_unavailable"
            ),
            "source_facts": {
                "kind": "asset_research_reports",
                "artifacts": source_artifacts,
                "research_facts_available": all_artifacts_readable,
                "freshness_status": "not_defined",
                "currency_status": "not_declared",
            },
            "account_total": {
                "status": "not_applicable_research",
                "currency": None,
                "value": None,
            },
            "accounts": [],
            "strategies": [],
            "strategy_attribution": _research_attribution(),
            "coverage": {
                "complete": False,
                "research_facts_available": all_artifacts_readable,
                "account_facts_complete": False,
                "strategy_attribution_complete": False,
                "code": coverage_code,
            },
        }


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _published_research_decision(report_sections: Any) -> dict[str, Any] | None:
    """Select non-valuational fields from the persisted published decision only."""

    if not isinstance(report_sections, dict):
        return None
    decision = report_sections.get("published_decision")
    if not isinstance(decision, dict):
        return None
    allowed_values = {
        "asset_type": {"stock", "bond", "fund", "futures", "option", "fx", "crypto"},
        "market_view": {"BULLISH", "BEARISH", "NEUTRAL", "INDETERMINATE"},
        "normalized_direction": {"LONG", "SHORT", "NEUTRAL", "INDETERMINATE"},
        "recommendation": {"BUY", "SELL", "HOLD", "AVOID"},
        "actionability": {
            "ACTIONABLE",
            "RESEARCH_ONLY",
            "INSUFFICIENT_DATA",
            "REGION_RESTRICTED",
        },
        "quality_status": {"ELIGIBLE", "DEGRADED", "REJECTED"},
    }
    string_fields = (*allowed_values, "horizon_code")
    result = {
        field: value[:256] if isinstance(value, str) else None
        for field in string_fields
        if (value := decision.get(field)) is not None
    }
    if any(
        not isinstance(decision.get(field), str)
        or not decision[field]
        or len(decision[field]) > 256
        or not decision[field].isprintable()
        or (field in allowed_values and decision[field] not in allowed_values[field])
        for field in string_fields
    ):
        return None
    if decision.get("execution_disabled") is not True:
        return None
    result["execution_disabled"] = True
    return result


def _project_account_total(
    reads: list[tuple[str, AccountReadView | None, str | None]], currency: str
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
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
    return (
        rows,
        {"status": status_value, "currency": currency, "value": projected_total},
        _account_snapshot_consistency(reads),
    )


_ACCOUNT_OBSERVED_AT_RE = re.compile(
    r"^(?P<whole>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d+))?(?P<offset>Z|[+-]\d{2}:\d{2})$"
)


def _account_snapshot_consistency(
    reads: list[tuple[str, AccountReadView | None, str | None]],
) -> dict[str, Any]:
    """Report independent account cuts and their exact observed-time spread."""

    timed_reads: list[tuple[int, str]] = []
    for _, view, _ in reads:
        if view is None:
            continue
        observed_at = view.observed_at_utc
        observed_at_ns = _account_observed_at_ns(observed_at)
        if observed_at_ns is not None and observed_at is not None:
            timed_reads.append((observed_at_ns, observed_at))

    earliest = min(timed_reads, key=lambda item: item[0]) if timed_reads else None
    latest = max(timed_reads, key=lambda item: item[0]) if timed_reads else None
    result: dict[str, Any] = {
        "cut_model": "independent_per_account",
        "atomic": False,
        "member_read_count": len(reads),
        "observed_at_count": len(timed_reads),
        "earliest_observed_at_utc": earliest[1] if earliest else None,
        "latest_observed_at_utc": latest[1] if latest else None,
        "skew_ns": None,
        "skew_policy": "reported_without_threshold",
    }
    if not reads:
        result["status"] = "not_collected"
    elif len(timed_reads) != len(reads):
        result["status"] = "observation_time_incomplete"
    elif len(reads) == 1:
        result["status"] = "single_account_cut"
    else:
        skew_ns = max(item[0] for item in timed_reads) - min(
            item[0] for item in timed_reads
        )
        result["skew_ns"] = str(skew_ns)
        result["status"] = (
            "same_observation_time_independent_cuts"
            if skew_ns == 0
            else "different_observation_times_independent_cuts"
        )
    return result


def _provider_snapshot_consistency(
    reads: list[tuple[str, AccountReadView | None, str | None]],
) -> dict[str, Any]:
    """Report independent Gateway observation cuts without claiming atomicity."""

    observations: list[tuple[int, str, str]] = []
    missing_observation = False
    missing_time = False
    consistency_modes: set[str] = set()
    coverage_states: list[bool] = []
    for member_ref, view, _ in reads:
        observation = view.provider_observation if view is not None else None
        if not isinstance(observation, Mapping):
            missing_observation = True
            continue
        coverage_states.append(
            observation["balances_complete"] and observation["positions_complete"]
        )
        completed_at = observation["completed_at_utc"]
        completed_at_ns = _account_observed_at_ns(completed_at)
        if completed_at_ns is None:
            missing_time = True
        else:
            observations.append((completed_at_ns, completed_at, member_ref))
        consistency_modes.add(observation["consistency"])

    earliest = min(observations, key=lambda item: item[0]) if observations else None
    latest = max(observations, key=lambda item: item[0]) if observations else None
    result: dict[str, Any] = {
        "cut_model": "independent_provider_observation_per_account",
        "atomic": False,
        "member_read_count": len(reads),
        "observation_count": len(observations),
        "consistency_modes": sorted(consistency_modes),
        "coverage_status": (
            "not_established"
            if not reads or missing_observation
            else "complete"
            if all(coverage_states) and len(coverage_states) == len(reads)
            else "incomplete"
        ),
        "coverage_complete": (
            all(coverage_states) and len(coverage_states) == len(reads)
            if reads and not missing_observation
            else None
        ),
        "earliest_completed_at_utc": earliest[1] if earliest else None,
        "latest_completed_at_utc": latest[1] if latest else None,
        "skew_ns": None,
        "skew_policy": "reported_without_threshold",
    }
    if not reads:
        result["status"] = "not_collected"
    elif missing_observation:
        result["status"] = "observation_absent_or_unavailable"
    elif missing_time or len(observations) != len(reads):
        result["status"] = "observation_time_incomplete"
    elif len(reads) == 1:
        result["status"] = "single_account_observation_cut"
    else:
        skew_ns = max(item[0] for item in observations) - min(
            item[0] for item in observations
        )
        result["skew_ns"] = str(skew_ns)
        result["status"] = (
            "same_completion_time_independent_cuts"
            if skew_ns == 0
            else "different_completion_times_independent_cuts"
        )
    return result


def _account_observed_at_ns(value: str | None) -> int | None:
    """Parse an aware ISO timestamp exactly to nanoseconds, without defaulting."""

    if not isinstance(value, str):
        return None
    match = _ACCOUNT_OBSERVED_AT_RE.fullmatch(value)
    if match is None:
        return None
    fraction = match.group("fraction") or ""
    if len(fraction) > 9 and any(digit != "0" for digit in fraction[9:]):
        return None
    offset = match.group("offset")
    try:
        parsed = datetime.fromisoformat(
            match.group("whole") + ("+00:00" if offset == "Z" else offset)
        )
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    utc_second = parsed.astimezone(timezone.utc).replace(microsecond=0)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = utc_second - epoch
    whole_seconds = delta.days * 86_400 + delta.seconds
    fractional_ns = int(fraction[:9].ljust(9, "0")) if fraction else 0
    return whole_seconds * 1_000_000_000 + fractional_ns


def _account_row(
    member_ref: str,
    view: AccountReadView,
    included: bool,
    duplicate_of: str | None,
    detail_code: str | None,
) -> dict[str, Any]:
    return {
        "member_ref": member_ref,
        "account_ref": view.account_ref,
        # These public source coordinates identify this account read without
        # returning the private AccountKey or its stable internal identifier.
        "execution_domain_ref": view.execution_domain_ref,
        "source_service_id": view.source_service_id,
        "session_generation": view.session_generation,
        "cursor": view.cursor,
        "currency": view.currency,
        "quality": view.quality.value,
        "has_current_facts": view.has_current_facts,
        "cash": _decimal_text(view.cash),
        "value": _decimal_text(view.value),
        "observed_at_utc": view.observed_at_utc,
        "received_age_seconds": view.received_age_seconds,
        "fresh_for_seconds": view.fresh_for_seconds,
        "positions_count": view.positions_count,
        "open_orders_count": view.open_orders_count,
        "included_in_total": included,
        "duplicate_of_ref": duplicate_of,
        "detail_code": detail_code,
        "provider_observation": _public_provider_observation_projection(view),
    }


def _public_provider_observation_projection(view: AccountReadView) -> dict[str, Any]:
    """Expose account observations and their coverage while omitting account keys."""

    observation = view.provider_observation
    if not isinstance(observation, Mapping):
        if view.quality is ReadQuality.UNAVAILABLE:
            return {
                "status": "unavailable",
                "code": view.detail_code or "ACCOUNT_OBSERVATION_UNAVAILABLE",
            }
        return {"status": "absent", "code": "PROVIDER_OBSERVATION_NOT_PROJECTED"}

    row_times = [
        row["observed_at_utc"]
        for row in (*observation["balances"], *observation["positions"])
    ]
    if observation["valuation"] is not None:
        row_times.append(observation["valuation"]["observed_at_utc"])
    parsed_times = [
        (observed_ns, observed_at)
        for observed_at in row_times
        if (observed_ns := _account_observed_at_ns(observed_at)) is not None
    ]
    earliest = min(parsed_times, key=lambda item: item[0]) if parsed_times else None
    latest = max(parsed_times, key=lambda item: item[0]) if parsed_times else None
    row_skew_ns = (
        str(latest[0] - earliest[0]) if earliest is not None and latest is not None else None
    )
    positions = [
        {
            "resource": dict(position["resource"]),
            "instrument": dict(position["instrument"]),
            "side": position["side"],
            "quantity": position["quantity"],
            "qty_unit": position["qty_unit"],
            "average_price": position["average_price"],
            "price_currency": position["price_currency"],
            "observed_at_utc": position["observed_at_utc"],
            "valuation_inputs": {
                "mark_price": {"status": "missing", "value": None},
                "contract_multiplier": {"status": "unsupported", "value": None},
                "fx_rate": {"status": "unsupported", "value": None},
                "market_value": {"status": "not_calculated", "value": None},
            },
        }
        for position in observation["positions"]
    ]
    return {
        "status": "stale" if view.quality is ReadQuality.STALE else "available",
        "quality": view.quality.value,
        "source": "AUTHORIZED_PROVIDER_ACCOUNT_OBSERVATION",
        "observation_id": observation["observation_id"],
        "session_generation": view.session_generation,
        "cursor": view.cursor,
        "consistency": observation["consistency"],
        "cut": {
            "started_at_utc": observation["started_at_utc"],
            "completed_at_utc": observation["completed_at_utc"],
            "earliest_row_observed_at_utc": earliest[1] if earliest else None,
            "latest_row_observed_at_utc": latest[1] if latest else None,
            "row_skew_ns": row_skew_ns,
            "row_observed_at_count": len(parsed_times),
            "row_count": len(row_times),
        },
        "coverage": {
            "resources": [dict(resource) for resource in observation["coverage"]],
            "balances_complete": observation["balances_complete"],
            "positions_complete": observation["positions_complete"],
            "state": (
                "complete"
                if observation["balances_complete"] and observation["positions_complete"]
                else "incomplete"
            ),
        },
        "valuation": (
            dict(observation["valuation"]) if observation["valuation"] is not None else None
        ),
        "balances": [
            {
                "resource": dict(balance["resource"]),
                "currency": balance["currency"],
                "total": balance["total"],
                "available": balance["available"],
                "locked": balance["locked"],
                "observed_at_utc": balance["observed_at_utc"],
            }
            for balance in observation["balances"]
        ],
        "positions": positions,
    }


def _public_financial_projection(source: Mapping[str, Any]) -> dict[str, Any]:
    """Expose persisted financial facts without account keys or execution scopes."""

    if "financial" not in source:
        return {"status": "absent"}

    financial = source["financial"]
    if not isinstance(financial, Mapping) or type(financial.get("available")) is not bool:
        raise ValueError("INVALID_ACCOUNT_BOOK_FINANCIAL")
    if financial["available"] is False:
        return {
            "status": "unavailable",
            "code": financial["code"],
            "freshness": financial["freshness"],
            "cut_relationship": financial["cut_relationship"],
        }

    ledger_cut = financial["ledger_cut"]
    public_cut = {
        "owner_directory_revision": ledger_cut["owner_directory_revision"],
        # Keep nanosecond cursors exact when JSON is parsed by JavaScript.
        "captured_at_ns": str(ledger_cut["captured_at_ns"]),
        "watermarks": [
            {
                "source_kind": item["source_kind"],
                "source_ref": item["source_ref"],
                "generation": item["generation"],
                "cursor": item["cursor"],
                "as_of_ns": str(item["as_of_ns"]),
            }
            for item in ledger_cut["watermarks"]
        ],
    }
    return {
        "status": "available",
        "source": financial["source"],
        "freshness": financial["freshness"],
        "cut_relationship": financial["cut_relationship"],
        "complete": financial["complete"],
        "state": financial["state"],
        "ledger_cut": public_cut,
        "books": [
            {
                "owner": {
                    "kind": book["owner"]["kind"],
                    "owner_ref": book["owner"]["owner_ref"],
                },
                "cash": list(book["cash"]),
                "positions": [
                    {
                        "instrument": position["instrument"],
                        "quantity": position["quantity"],
                        "cost_basis": position["cost_basis"],
                        "cost_currency": position["cost_currency"],
                        "cost_method": position["cost_method"],
                        "product_model": position["product_model"],
                        "metadata_version": position["metadata_version"],
                    }
                    for position in book["positions"]
                ],
                "cumulative_fees": list(book["cumulative_fees"]),
                "realized_pnl": list(book["realized_pnl"]),
                "cost_basis_complete": book["cost_basis_complete"],
            }
            for book in financial["books"]
        ],
        "unallocated": {
            "cash": list(financial["unallocated"]["cash"]),
            "positions": [
                {"instrument": instrument, "quantity": quantity}
                for instrument, quantity in financial["unallocated"]["positions"]
            ],
            "fees": list(financial["unallocated"]["fees"]),
        },
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


def _research_attribution() -> dict[str, Any]:
    return {
        "status": "not_applicable_research",
        "strategy_count": 0,
        "attributed_value": None,
        "unattributed_account_value": None,
        "residual_basis": "research reports do not establish account or strategy holdings",
    }


def _imported_attribution() -> dict[str, Any]:
    return {
        "status": "not_applicable_imported",
        "strategy_count": 0,
        "attributed_value": None,
        "unattributed_account_value": None,
        "residual_basis": "imported transaction materials do not establish account holdings",
    }


def _unavailable_import_artifact(source_status: str) -> dict[str, Any]:
    return {
        "status": source_status,
        "source_integrity_status": "unavailable",
        "import_format": None,
        "source_schema_version": None,
        "source_sha256": None,
        "source_as_of": None,
        "source_as_of_status": "unavailable",
        "source_currency": None,
        "currency_status": "not_declared",
        "freshness_status": "not_defined",
        "source_row_count": None,
        "trade_date_rows_present": None,
        "trade_date_coverage": "unavailable",
        "source_metadata_status": "unavailable",
        "source_rows_available": False,
    }


def _unavailable_imported_projection(base: dict[str, Any], code: str) -> dict[str, Any]:
    return {
        **base,
        "source_status": "imported_materials_unavailable",
        "source_facts": {
            "kind": "portfolio_ledger_import_versions",
            "artifacts": [],
            "source_materials_verified": False,
            "freshness_status": "not_defined",
            "account_value_status": "not_applicable_imported",
        },
        "account_total": {
            "status": "not_applicable_imported",
            "currency": None,
            "value": None,
        },
        "accounts": [],
        "strategies": [],
        "strategy_attribution": _imported_attribution(),
        "coverage": {
            "complete": False,
            "account_facts_complete": False,
            "source_materials_verified": False,
            "code": code,
        },
    }


def _has_explicit_trade_date(source_row: dict[str, Any]) -> bool:
    value = source_row.get("trade_date")
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    return parsed_date.isoformat() == value


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
