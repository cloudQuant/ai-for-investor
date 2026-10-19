"""Read-only inventory and fail-closed cutover checks for the legacy paper ledger.

This module never transfers balances or records.  The current managed paper
owner cannot import the legacy ledger's orders, positions, fees, or unresolved
work, so only a verified empty account with an exactly matching opening cash
state can be switched to a managed owner.  Stateful legacy accounts remain
available in their legacy view and are refused by managed submission.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, AsyncIterator, Mapping

from sqlalchemy import inspect as sa_inspect

MAX_INVENTORY_ROWS_PER_TABLE = 10_000


@dataclass(frozen=True)
class LegacyPaperInventory:
    account_id: str
    owner_id: str
    complete: bool
    digest: str | None
    account: Mapping[str, Any]
    order_count: int | None
    position_count: int | None
    trade_count: int | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyPaperCutoverAssessment:
    ready: bool
    inventory_sha256: str | None
    reasons: tuple[str, ...]
    order_count: int | None
    position_count: int | None
    trade_count: int | None


class LegacyPaperInventoryError(RuntimeError):
    """A bounded inventory could not be read without making a claim."""

    def __init__(self, code: str, *, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(code)


async def inspect_legacy_paper_account(
    service: Any,
    account_id: str,
    owner_id: str,
    *,
    max_rows_per_table: int = MAX_INVENTORY_ROWS_PER_TABLE,
) -> LegacyPaperInventory:
    """Read every persisted row for one account and return a stable digest.

    Counts are checked before and after each bounded read.  Closed/zero-size
    positions are included by querying the repository directly rather than the
    user-facing open-position projection.
    """

    if not _identifier(account_id) or not _identifier(owner_id):
        raise LegacyPaperInventoryError("INVALID_SELECTOR")
    if type(max_rows_per_table) is not int or not 1 <= max_rows_per_table <= 100_000:
        raise LegacyPaperInventoryError("INVALID_INVENTORY_LIMIT")

    account = await service.get_account(account_id)
    if account is None:
        raise LegacyPaperInventoryError("LEGACY_ACCOUNT_NOT_FOUND")
    account_fields = _model_row(account)
    reasons: list[str] = []
    if account_fields.get("user_id") != owner_id:
        reasons.append("legacy_owner_mismatch")

    table_rows: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int | None] = {}
    complete = True
    for table_name, repo_name in (
        ("orders", "order_repo"),
        ("positions", "position_repo"),
        ("trades", "trade_repo"),
    ):
        repo = getattr(service, repo_name, None)
        if repo is None:
            complete = False
            reasons.append(f"{table_name}_repository_unavailable")
            counts[table_name] = None
            continue
        filters = {"account_id": account_id}
        try:
            before = await repo.count(filters=filters)
            if type(before) is not int or before < 0:
                raise ValueError("invalid repository count")
            counts[table_name] = before
            if before > max_rows_per_table:
                complete = False
                reasons.append(f"{table_name}_inventory_limit_exceeded")
                table_rows[table_name] = []
                continue
            rows = await repo.list(filters=filters, skip=0, limit=before + 1)
            after = await repo.count(filters=filters)
            if type(after) is not int or after != before or len(rows) != before:
                complete = False
                reasons.append(f"{table_name}_inventory_changed_during_read")
                table_rows[table_name] = []
                continue
            normalized = [_model_row(row) for row in rows]
            normalized.sort(key=lambda row: str(row.get("id", "")))
            if len({str(row.get("id", "")) for row in normalized}) != len(normalized):
                complete = False
                reasons.append(f"{table_name}_duplicate_row_id")
                table_rows[table_name] = []
                continue
            table_rows[table_name] = normalized
        except LegacyPaperInventoryError:
            raise
        except Exception:
            complete = False
            reasons.append(f"{table_name}_inventory_unavailable")
            counts.setdefault(table_name, None)
            table_rows[table_name] = []

    digest: str | None = None
    if complete:
        try:
            raw = json.dumps(
                {
                    "schema": "afi.legacy-paper-inventory.v1",
                    "account": account_fields,
                    "orders": table_rows["orders"],
                    "positions": table_rows["positions"],
                    "trades": table_rows["trades"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            complete = False
            reasons.append("inventory_contains_unsupported_value")
        else:
            digest = hashlib.sha256(raw).hexdigest()

    return LegacyPaperInventory(
        account_id=account_id,
        owner_id=owner_id,
        complete=complete,
        digest=digest,
        account=account_fields,
        order_count=counts.get("orders"),
        position_count=counts.get("positions"),
        trade_count=counts.get("trades"),
        reasons=tuple(dict.fromkeys(reasons)),
    )


async def inspect_stable_legacy_paper_account(
    service: Any,
    account_id: str,
    owner_id: str,
    *,
    max_rows_per_table: int = MAX_INVENTORY_ROWS_PER_TABLE,
) -> LegacyPaperInventory:
    """Take two bounded read-only inventories and reject any observed change."""

    first = await inspect_legacy_paper_account(
        service, account_id, owner_id, max_rows_per_table=max_rows_per_table
    )
    second = await inspect_legacy_paper_account(
        service, account_id, owner_id, max_rows_per_table=max_rows_per_table
    )
    if not first.complete or not second.complete or first.digest != second.digest:
        reasons = tuple(
            dict.fromkeys((*first.reasons, *second.reasons, "inventory_not_stable"))
        )
        return LegacyPaperInventory(
            account_id=account_id,
            owner_id=owner_id,
            complete=False,
            digest=None,
            account=second.account,
            order_count=second.order_count,
            position_count=second.position_count,
            trade_count=second.trade_count,
            reasons=reasons,
        )
    return second


def assess_empty_account_cutover(
    inventory: LegacyPaperInventory,
    binding: Any,
) -> LegacyPaperCutoverAssessment:
    """Assess only a pristine-account cutover; no nonempty migration is claimed."""

    reasons = list(inventory.reasons)
    if not inventory.complete or inventory.digest is None:
        reasons.append("inventory_incomplete")
    if inventory.account.get("user_id") != inventory.owner_id:
        reasons.append("legacy_owner_mismatch")
    if inventory.account.get("is_active") is not True:
        reasons.append("legacy_account_inactive")
    if inventory.order_count != 0:
        reasons.append("legacy_orders_present")
    if inventory.position_count != 0:
        reasons.append("legacy_positions_present")
    if inventory.trade_count != 0:
        reasons.append("legacy_trades_present")

    initial_cash = _decimal(inventory.account.get("initial_cash"))
    current_cash = _decimal(inventory.account.get("current_cash"))
    total_equity = _decimal(inventory.account.get("total_equity"))
    profit_loss = _decimal(inventory.account.get("profit_loss"))
    profit_loss_pct = _decimal(inventory.account.get("profit_loss_pct"))
    legacy_fee_rate = _decimal(inventory.account.get("commission_rate"))
    slippage_rate = _decimal(inventory.account.get("slippage_rate"))
    if None in (
        initial_cash,
        current_cash,
        total_equity,
        profit_loss,
        profit_loss_pct,
        legacy_fee_rate,
        slippage_rate,
    ):
        reasons.append("legacy_economic_state_invalid")
    else:
        if (
            current_cash != initial_cash
            or total_equity != initial_cash
            or profit_loss != 0
            or profit_loss_pct != 0
        ):
            reasons.append("legacy_cash_or_equity_not_pristine")
        configured_cash = _decimal(_binding_value(binding, "initial_cash"))
        if configured_cash is None or configured_cash != initial_cash:
            reasons.append("managed_opening_cash_mismatch")
        configured_fee_rate = _decimal(_binding_value(binding, "fee_rate"))
        if configured_fee_rate is None or configured_fee_rate != legacy_fee_rate:
            reasons.append("managed_fee_rate_mismatch")
        if slippage_rate != 0:
            reasons.append("legacy_slippage_not_representable")

    initial_fees = _decimal(_binding_value(binding, "initial_fees"))
    if initial_fees is None or initial_fees != 0:
        reasons.append("managed_initial_fees_not_zero")
    opening_positions = _binding_value(binding, "opening_positions")
    if opening_positions not in ((), [], None):
        reasons.append("managed_opening_positions_not_empty")

    unique = tuple(dict.fromkeys(reasons))
    return LegacyPaperCutoverAssessment(
        ready=not unique,
        inventory_sha256=inventory.digest,
        reasons=unique,
        order_count=inventory.order_count,
        position_count=inventory.position_count,
        trade_count=inventory.trade_count,
    )


def paper_binding_fingerprint(binding: Any) -> str:
    """Hash trusted paper identity and immutable owner-domain configuration."""

    payload = _paper_binding_payload(binding)
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def prepare_empty_account_cutover(
    service: Any,
    owner_subject: str,
    binding: Any,
) -> Any:
    """Create or verify one persistent empty-account cutover receipt.

    The final inventory read and receipt insert share an account-row write
    lock. Legacy writers take the same lock while holding a durable lease, and
    the migration installs database triggers that fence stale application
    binaries after this receipt becomes active.
    """

    from sqlalchemy import select, update
    from sqlalchemy.exc import IntegrityError

    from app.db.database import async_session_maker
    from app.models.legacy_paper_cutover import (
        LegacyPaperCutoverReceipt,
        LegacyPaperWriterLease,
    )
    from app.models.paper_trading import Account

    if not _identifier(owner_subject):
        raise LegacyPaperInventoryError("INVALID_SELECTOR")
    payload = _paper_binding_payload(binding)
    if payload["legacy_account_id"] != _binding_value(binding, "legacy_account_id"):
        raise LegacyPaperInventoryError("INVALID_PAPER_BINDING")

    preflight = await inspect_stable_legacy_paper_account(
        service, payload["legacy_account_id"], owner_subject
    )
    assessment = assess_empty_account_cutover(preflight, binding)
    if not assessment.ready:
        raise LegacyPaperInventoryError(
            "LEGACY_PAPER_CUTOVER_NOT_READY",
            details={
                "source": "legacy",
                "inventory_sha256": assessment.inventory_sha256,
                "order_count": assessment.order_count,
                "position_count": assessment.position_count,
                "trade_count": assessment.trade_count,
                "reasons": list(assessment.reasons),
            },
        )

    try:
        async with async_session_maker() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(LegacyPaperCutoverReceipt).where(
                        LegacyPaperCutoverReceipt.legacy_account_id
                        == payload["legacy_account_id"]
                    )
                )
                if existing is not None:
                    _require_receipt_matches(existing, owner_subject, payload, preflight.digest)
                    return existing
                await session.execute(
                    update(Account)
                    .where(Account.id == payload["legacy_account_id"])
                    .values(updated_at=Account.updated_at)
                )
                account = await session.scalar(
                    select(Account)
                    .where(Account.id == payload["legacy_account_id"])
                    .with_for_update()
                )
                if account is None:
                    raise LegacyPaperInventoryError("LEGACY_ACCOUNT_NOT_FOUND")
                if account.user_id != owner_subject:
                    raise LegacyPaperInventoryError("LEGACY_OWNER_MISMATCH")

                active_writers = await session.scalar(
                    select(LegacyPaperWriterLease.id)
                    .where(LegacyPaperWriterLease.account_id == account.id)
                    .limit(1)
                )
                if active_writers is not None:
                    raise LegacyPaperInventoryError("LEGACY_WRITES_IN_PROGRESS")

                locked = await _inspect_inventory_in_session(
                    session, account, account_id=account.id, owner_id=owner_subject
                )
                locked_assessment = assess_empty_account_cutover(locked, binding)
                if (
                    not locked_assessment.ready
                    or locked.digest != preflight.digest
                    or locked.digest is None
                ):
                    raise LegacyPaperInventoryError(
                        "LEGACY_PAPER_CUTOVER_NOT_READY",
                        details={
                            "source": "legacy",
                            "inventory_sha256": locked.digest,
                            "reasons": list(
                                dict.fromkeys(
                                    (*locked_assessment.reasons, "inventory_changed_at_cutover")
                                )
                            ),
                        },
                    )

                receipt = LegacyPaperCutoverReceipt(
                    legacy_account_id=account.id,
                    owner_subject=owner_subject,
                    state="ACTIVE",
                    receipt_version=1,
                    source_inventory_sha256=locked.digest,
                    source_kind="empty_account",
                    source_import_receipt_id=None,
                    source_import_generation=None,
                    target_import_sha256=None,
                    binding_sha256=paper_binding_fingerprint(binding),
                    paper_domain_sha256=payload["paper_domain_sha256"],
                    scope_ref=payload["scope_ref"],
                    account_ref=payload["account_ref"],
                    execution_domain_ref=payload["execution_domain_ref"],
                    strategy_ref=payload["strategy_ref"],
                    initial_cash=payload["initial_cash"],
                    initial_fees=payload["initial_fees"],
                    fee_rate=payload["fee_rate"],
                    source_order_count=0,
                    source_position_count=0,
                    source_trade_count=0,
                )
                session.add(receipt)
                await session.flush()
                return receipt
    except LegacyPaperInventoryError:
        raise
    except IntegrityError:
        existing = await get_legacy_paper_cutover_receipt(payload["legacy_account_id"])
        if existing is None:
            raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_CONFLICT") from None
        _require_receipt_matches(existing, owner_subject, payload, preflight.digest)
        return existing
    except Exception:
        try:
            existing = await get_legacy_paper_cutover_receipt(payload["legacy_account_id"])
        except LegacyPaperInventoryError:
            existing = None
        if existing is not None:
            _require_receipt_matches(existing, owner_subject, payload, preflight.digest)
            return existing
        raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_STORE_UNAVAILABLE") from None


async def get_legacy_paper_cutover_receipt(account_id: str) -> Any | None:
    """Read the durable receipt without mutating or completing a cutover."""

    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.legacy_paper_cutover import LegacyPaperCutoverReceipt

    if not _identifier(account_id):
        raise LegacyPaperInventoryError("INVALID_SELECTOR")
    try:
        async with async_session_maker() as session:
            return await session.scalar(
                select(LegacyPaperCutoverReceipt).where(
                    LegacyPaperCutoverReceipt.legacy_account_id == account_id,
                    LegacyPaperCutoverReceipt.state == "ACTIVE",
                )
            )
    except Exception:
        raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_STORE_UNAVAILABLE") from None


async def require_active_paper_cutover_receipt(
    account_id: str,
    owner_subject: str,
    binding: Any,
    *,
    service_factory: Any | None = None,
    import_binding: Any | None = None,
    target_worker: Any | None = None,
) -> Any:
    """Require the persisted qualification, current binding and no legacy lease."""

    from sqlalchemy import select

    from app.db.database import async_session_maker
    from app.models.legacy_paper_cutover import (
        LegacyPaperCutoverReceipt,
        LegacyPaperWriterLease,
    )

    payload = _paper_binding_payload(binding)
    if account_id != payload["legacy_account_id"]:
        raise LegacyPaperInventoryError("PAPER_BINDING_ACCOUNT_MISMATCH")
    try:
        async with async_session_maker() as session:
            receipt = await session.scalar(
                select(LegacyPaperCutoverReceipt).where(
                    LegacyPaperCutoverReceipt.legacy_account_id == account_id,
                    LegacyPaperCutoverReceipt.state == "ACTIVE",
                )
            )
            if receipt is None:
                raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_REQUIRED")
            active_writer = await session.scalar(
                select(LegacyPaperWriterLease.id)
                .where(LegacyPaperWriterLease.account_id == account_id)
                .limit(1)
            )
            if active_writer is not None:
                raise LegacyPaperInventoryError("LEGACY_WRITES_IN_PROGRESS")
    except LegacyPaperInventoryError:
        raise
    except Exception:
        raise LegacyPaperInventoryError("LEGACY_PAPER_CUTOVER_STORE_UNAVAILABLE") from None

    source_kind = getattr(receipt, "source_kind", "empty_account")
    if source_kind == "empty_account":
        _require_receipt_matches(
            receipt,
            owner_subject,
            payload,
            receipt.source_inventory_sha256,
        )
    elif source_kind == "imported_legacy":
        if (
            not callable(service_factory)
            or import_binding is None
            or target_worker is None
        ):
            raise LegacyPaperInventoryError("LEGACY_IMPORT_BINDING_REQUIRED")
        try:
            from app.services.legacy_paper_import_migration import (
                require_imported_paper_cutover_qualification,
            )

            await require_imported_paper_cutover_qualification(
                receipt,
                service_factory(),
                owner_subject,
                binding,
                import_binding,
                target_worker=target_worker,
            )
        except LegacyPaperInventoryError:
            raise
        except Exception:
            raise LegacyPaperInventoryError(
                "LEGACY_IMPORT_CUTOVER_BINDING_MISMATCH"
            ) from None
    else:
        raise LegacyPaperInventoryError("MANAGED_PAPER_CUTOVER_BINDING_MISMATCH")
    return receipt


@asynccontextmanager
async def legacy_paper_writer_lease(account_id: str) -> AsyncIterator[None]:
    """Serialize a legacy mutation against cutover and record its live writer."""

    from sqlalchemy import select, update

    from app.db.database import async_session_maker
    from app.models.legacy_paper_cutover import (
        LegacyPaperCutoverReceipt,
        LegacyPaperWriterLease,
    )
    from app.models.paper_trading import Account

    if not _identifier(account_id):
        raise LegacyPaperInventoryError("INVALID_SELECTOR")
    lease_id: str | None = None
    try:
        async with async_session_maker() as session:
            async with session.begin():
                await session.execute(
                    update(Account)
                    .where(Account.id == account_id)
                    .values(updated_at=Account.updated_at)
                )
                account = await session.scalar(
                    select(Account).where(Account.id == account_id).with_for_update()
                )
                if account is not None:
                    receipt = await session.scalar(
                        select(LegacyPaperCutoverReceipt).where(
                            LegacyPaperCutoverReceipt.legacy_account_id == account_id
                        )
                    )
                    if receipt is not None:
                        raise LegacyPaperInventoryError("MANAGED_PAPER_LEGACY_ACCOUNT_FENCED")
                    lease_id = str(uuid.uuid4())
                    session.add(LegacyPaperWriterLease(id=lease_id, account_id=account_id))
    except LegacyPaperInventoryError:
        raise
    except Exception:
        receipt = None
        import_fence_is_known = False
        try:
            from app.models.legacy_paper_import import LegacyPaperImportReceipt

            async with async_session_maker() as session:
                receipt = await session.scalar(
                    select(LegacyPaperCutoverReceipt).where(
                        LegacyPaperCutoverReceipt.legacy_account_id == account_id
                    )
                )
                if receipt is None:
                    import_receipts = list(
                        (
                            await session.execute(
                                select(LegacyPaperImportReceipt)
                                .where(
                                    LegacyPaperImportReceipt.legacy_account_id == account_id,
                                    LegacyPaperImportReceipt.active_fence_key == account_id,
                                    LegacyPaperImportReceipt.state.in_(
                                        ("PREPARED", "COMMITTED", "ACTIVE")
                                    ),
                                )
                                .limit(2)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if len(import_receipts) == 1:
                        imported_receipt = import_receipts[0]
                        owner_subject = await session.scalar(
                            select(Account.user_id).where(Account.id == account_id)
                        )
                        import_fence_is_known = (
                            imported_receipt.legacy_account_id == account_id
                            and imported_receipt.active_fence_key == account_id
                            and imported_receipt.state in {"PREPARED", "COMMITTED", "ACTIVE"}
                            and imported_receipt.receipt_version == 1
                            and type(imported_receipt.generation) is int
                            and imported_receipt.generation > 0
                            and type(imported_receipt.owner_subject) is str
                            and imported_receipt.owner_subject == owner_subject
                        )
        except Exception:
            receipt = None
            import_fence_is_known = False
        if receipt is not None or import_fence_is_known:
            raise LegacyPaperInventoryError(
                "MANAGED_PAPER_LEGACY_ACCOUNT_FENCED"
            ) from None
        raise LegacyPaperInventoryError("LEGACY_WRITE_FENCE_UNAVAILABLE") from None

    try:
        yield
    finally:
        if lease_id is not None:
            try:
                async with async_session_maker() as session:
                    async with session.begin():
                        lease = await session.get(LegacyPaperWriterLease, lease_id)
                        if lease is not None:
                            await session.delete(lease)
            except Exception:
                raise LegacyPaperInventoryError("LEGACY_WRITE_LEASE_RELEASE_UNAVAILABLE") from None


async def _inspect_inventory_in_session(
    session: Any,
    account: Any,
    *,
    account_id: str,
    owner_id: str,
) -> LegacyPaperInventory:
    from sqlalchemy import select

    from app.models.paper_trading import Order, PaperTrade, Position

    account_fields = _model_row(account)
    reasons: list[str] = []
    if account_fields.get("user_id") != owner_id:
        reasons.append("legacy_owner_mismatch")
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int | None] = {}
    complete = True
    for name, model in (
        ("orders", Order),
        ("positions", Position),
        ("trades", PaperTrade),
    ):
        result = await session.execute(
            select(model)
            .where(model.account_id == account_id)
            .order_by(model.id.asc())
            .limit(MAX_INVENTORY_ROWS_PER_TABLE + 1)
        )
        rows = list(result.scalars().all())
        counts[name] = len(rows)
        if len(rows) > MAX_INVENTORY_ROWS_PER_TABLE:
            complete = False
            reasons.append(f"{name}_inventory_limit_exceeded")
            rows_by_name[name] = []
            continue
        normalized = [_model_row(row) for row in rows]
        if len({str(row.get("id", "")) for row in normalized}) != len(normalized):
            complete = False
            reasons.append(f"{name}_duplicate_row_id")
            rows_by_name[name] = []
        else:
            rows_by_name[name] = normalized

    digest: str | None = None
    if complete:
        try:
            raw = json.dumps(
                {
                    "schema": "afi.legacy-paper-inventory.v1",
                    "account": account_fields,
                    "orders": rows_by_name["orders"],
                    "positions": rows_by_name["positions"],
                    "trades": rows_by_name["trades"],
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            complete = False
            reasons.append("inventory_contains_unsupported_value")
        else:
            digest = hashlib.sha256(raw).hexdigest()
    return LegacyPaperInventory(
        account_id=account_id,
        owner_id=owner_id,
        complete=complete,
        digest=digest,
        account=account_fields,
        order_count=counts.get("orders"),
        position_count=counts.get("positions"),
        trade_count=counts.get("trades"),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _paper_binding_payload(binding: Any) -> dict[str, Any]:
    string_fields = (
        "mount",
        "scope_ref",
        "query_scope_ref",
        "legacy_account_id",
        "account_ref",
        "execution_domain_ref",
        "strategy_ref",
        "experiment_ref",
        "model_ref",
        "model_version",
        "quote_source_ref",
        "cash_currency",
        "paper_domain_sha256",
    )
    values: dict[str, str] = {}
    for name in string_fields:
        value = _binding_value(binding, name)
        if not _identifier(value):
            raise LegacyPaperInventoryError("INVALID_PAPER_BINDING", details={"field": name})
        values[name] = value
    if not _is_sha256(values["paper_domain_sha256"]):
        raise LegacyPaperInventoryError("INVALID_PAPER_BINDING", details={"field": "paper_domain_sha256"})
    decimals: dict[str, str] = {}
    for name in ("initial_cash", "initial_fees", "fee_rate", "fee_quantum"):
        value = _decimal(_binding_value(binding, name))
        if value is None or value < 0:
            raise LegacyPaperInventoryError("INVALID_PAPER_BINDING", details={"field": name})
        decimals[name] = format(value, "f")
    max_quote_age_ns = _binding_value(binding, "max_quote_age_ns")
    if type(max_quote_age_ns) is not int or max_quote_age_ns <= 0:
        raise LegacyPaperInventoryError("INVALID_PAPER_BINDING", details={"field": "max_quote_age_ns"})
    raw_versions = _binding_value(binding, "instrument_metadata_versions")
    if not isinstance(raw_versions, Mapping) or not raw_versions:
        raise LegacyPaperInventoryError(
            "INVALID_PAPER_BINDING", details={"field": "instrument_metadata_versions"}
        )
    versions: dict[str, str] = {}
    for instrument, version in raw_versions.items():
        if (
            not _identifier(instrument)
            or instrument != instrument.strip().upper()
            or not _identifier(version)
        ):
            raise LegacyPaperInventoryError("INVALID_PAPER_BINDING", details={"field": "instrument_metadata_versions"})
        versions[instrument] = version
    positions = _binding_value(binding, "opening_positions")
    if positions is None:
        positions = ()
    if type(positions) not in {tuple, list}:
        raise LegacyPaperInventoryError("INVALID_PAPER_BINDING", details={"field": "opening_positions"})
    return {
        **values,
        **decimals,
        "max_quote_age_ns": max_quote_age_ns,
        "instrument_metadata_versions": dict(sorted(versions.items())),
        "opening_positions": _canonical_value(positions),
    }


def _require_receipt_matches(
    receipt: Any,
    owner_subject: str,
    binding_payload: Mapping[str, Any],
    inventory_sha256: str | None,
) -> None:
    if (
        getattr(receipt, "state", None) != "ACTIVE"
        or getattr(receipt, "receipt_version", None) != 1
        or getattr(receipt, "source_kind", "empty_account") != "empty_account"
        or getattr(receipt, "source_import_receipt_id", None) is not None
        or getattr(receipt, "source_import_generation", None) is not None
        or getattr(receipt, "target_import_sha256", None) is not None
        or getattr(receipt, "source_order_count", None) != 0
        or getattr(receipt, "source_position_count", None) != 0
        or getattr(receipt, "source_trade_count", None) != 0
        or getattr(receipt, "owner_subject", None) != owner_subject
        or getattr(receipt, "source_inventory_sha256", None) != inventory_sha256
        or getattr(receipt, "binding_sha256", None)
        != hashlib.sha256(
            json.dumps(
                dict(binding_payload),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        or getattr(receipt, "paper_domain_sha256", None)
        != binding_payload.get("paper_domain_sha256")
    ):
        raise LegacyPaperInventoryError("MANAGED_PAPER_CUTOVER_BINDING_MISMATCH")


def _model_row(model: Any) -> dict[str, Any]:
    columns = getattr(getattr(type(model), "__table__", None), "columns", None)
    if columns is None:
        raise LegacyPaperInventoryError("INVENTORY_MODEL_UNSUPPORTED")
    mapper = sa_inspect(type(model))
    return {
        column.key: _canonical_value(
            getattr(model, mapper.get_property_by_column(column).key)
        )
        for column in columns
    }


def _canonical_value(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise TypeError("mapping keys must be text")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    if type(value) in {tuple, list}:
        return [_canonical_value(item) for item in value]
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimal")
        return format(value, "f")
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite float")
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    raise TypeError(type(value).__name__)


def _binding_value(binding: Any, name: str) -> Any:
    if isinstance(binding, Mapping):
        return binding.get(name)
    return getattr(binding, name, None)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value != "*"
        and len(value) <= 256
        and value.isprintable()
    )


def _is_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "LegacyPaperCutoverAssessment",
    "LegacyPaperInventory",
    "LegacyPaperInventoryError",
    "MAX_INVENTORY_ROWS_PER_TABLE",
    "assess_empty_account_cutover",
    "get_legacy_paper_cutover_receipt",
    "inspect_legacy_paper_account",
    "inspect_stable_legacy_paper_account",
    "legacy_paper_writer_lease",
    "paper_binding_fingerprint",
    "prepare_empty_account_cutover",
    "require_active_paper_cutover_receipt",
]
