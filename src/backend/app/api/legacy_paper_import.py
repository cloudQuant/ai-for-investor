"""Authenticated, deployment-bound migration of non-empty legacy Paper ledgers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.api.afi_owner_scope import require_persisted_owner_scope
from app.api.deps import get_current_user
from app.api.paper_trading import get_paper_trading_service
from app.api.service_read import resolve_paper_legacy_import_access
from app.models.legacy_paper_import import LegacyPaperImportReceiptView
from app.schemas.auth import TokenPayload
from app.services.legacy_paper_import_migration import (
    LegacyPaperImportError,
    get_legacy_paper_import_receipt,
    inspect_legacy_paper_import_target,
    migrate_nonempty_legacy_paper_account,
    rollback_legacy_paper_import,
)
from app.services.legacy_paper_migration import (
    LegacyPaperInventoryError,
    inspect_stable_legacy_paper_account,
)
from app.services.paper_trading_service import PaperTradingService
from app.services.service_read.client import ServiceReadUnavailableError

router = APIRouter(
    prefix="/legacy-paper-imports",
    tags=["Legacy Paper Import"],
    dependencies=[Depends(require_persisted_owner_scope)],
)


class _ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirmed: StrictBool

    @model_validator(mode="after")
    def require_confirmation(self) -> _ConfirmRequest:
        if self.confirmed is not True:
            raise ValueError("explicit confirmation is required")
        return self


class _RollbackRequest(_ConfirmRequest):
    source_inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


_CONFLICT_CODES = frozenset(
    {
        "ACTIVE_LEGACY_IMPORT_CANNOT_ROLL_BACK",
        "INVALID_LEGACY_IMPORT_TRANSITION",
        "LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE",
        "LEGACY_IMPORT_BINDING_MISMATCH",
        "LEGACY_IMPORT_GENERATION_ABORTED",
        "LEGACY_IMPORT_NOT_REPRESENTABLE",
        "LEGACY_INVENTORY_CHANGED",
        "LEGACY_INVENTORY_UNAVAILABLE",
        "LEGACY_OWNER_MISMATCH",
        "LEGACY_RUNTIME_INSTANCE_RELATION_UNPROVEN",
        "TARGET_ACCOUNT_ALREADY_OWNED",
        "TARGET_IMPORT_ACTIVATION_UNCERTAIN",
        "TARGET_IMPORT_ABORT_UNVERIFIED",
        "TARGET_IMPORT_BINDING_MISMATCH",
        "TARGET_IMPORT_GENERATION_ABORTED",
        "TARGET_IMPORT_OWNER_UNVERIFIED",
        "TARGET_IMPORT_RECEIPT_MISSING",
        "TARGET_IMPORT_STATE_CONFLICT",
        "TARGET_IMPORT_STATUS_INVALID",
        "TARGET_SCOPE_MISMATCH",
        "TARGET_WRITER_UNAVAILABLE",
    }
)
_NOT_FOUND_CODES = frozenset(
    {"LEGACY_ACCOUNT_NOT_FOUND", "LEGACY_IMPORT_RECEIPT_NOT_FOUND"}
)
_BAD_REQUEST_CODES = frozenset(
    {
        "INVALID_PAPER_BINDING",
        "INVALID_SELECTOR",
        "INVALID_SYMBOL_BINDING",
        "LEGACY_PNL_NOT_RECONCILED",
    }
)
_FORBIDDEN_CODES = frozenset({"LEGACY_OWNER_MISMATCH", "LEGACY_IMPORT_BINDING_MISMATCH"})


def _http_error(code: str, *, inventory: bool = False) -> HTTPException:
    if code in _FORBIDDEN_CODES:
        http_status = status.HTTP_403_FORBIDDEN
    elif code in _NOT_FOUND_CODES:
        http_status = status.HTTP_404_NOT_FOUND
    elif code in _BAD_REQUEST_CODES:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif code in _CONFLICT_CODES:
        http_status = status.HTTP_409_CONFLICT
    else:
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
        if code not in {
            "LEGACY_IMPORT_STORE_UNAVAILABLE",
            "TARGET_IMPORT_CLIENT_UNAVAILABLE",
            "TARGET_IMPORT_REPLY_INVALID",
            "TARGET_IMPORT_RPC_FAILED",
            "TARGET_IMPORT_RPC_UNAVAILABLE",
            "TARGET_IMPORT_STATUS_INVALID",
            "TARGET_IMPORT_UNAVAILABLE",
            "TARGET_IMPORT_PREPARE_UNCERTAIN",
            "TARGET_IMPORT_ACTIVATE_UNCERTAIN",
            "TARGET_IMPORT_ABORT_UNCERTAIN",
            "TARGET_IMPORT_INVALID",
            "EXECUTION_IMPORT_CONTRACT_UNAVAILABLE",
            "LEGACY_INVENTORY_LIMIT_EXCEEDED",
            "LEGACY_CONTEXT_LIMIT_EXCEEDED",
        }:
            code = "LEGACY_INVENTORY_UNAVAILABLE" if inventory else "LEGACY_IMPORT_UNAVAILABLE"
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "message": "The authorized legacy Paper import could not complete."},
    )


def _receipt_payload(receipt: LegacyPaperImportReceiptView | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        "receipt_id": receipt.receipt_id,
        "generation": receipt.generation,
        "state": receipt.state,
        "source_inventory_sha256": receipt.source_inventory_sha256,
        "target_import_sha256": receipt.target_import_sha256,
        "target_domain_sha256": receipt.target_domain_sha256,
        "binding_sha256": receipt.binding_sha256,
        "target_scope_key": receipt.target_scope_key,
        "target_account_key": receipt.target_account_key,
        "cash_currency": receipt.cash_currency,
        "opening_cash": receipt.opening_cash,
        "cumulative_fees": receipt.cumulative_fees,
        "unallocated_equity_residual": receipt.unallocated_equity_residual,
        "source_order_count": receipt.source_order_count,
        "source_position_count": receipt.source_position_count,
        "source_trade_count": receipt.source_trade_count,
        "preserved_context_sha256": receipt.preserved_context_sha256,
        "created_at": _timestamp(receipt.created_at),
        "updated_at": _timestamp(receipt.updated_at),
        "legacy_ledger": "retained_read_only",
        "imported_rows_are_exchange_facts": False,
        "preserved_controls_activated": False,
    }


def _timestamp(value: datetime) -> str:
    aware = value.replace(tzinfo=value.tzinfo or timezone.utc)
    return aware.isoformat()


def _access(current_user: TokenPayload, legacy_account_id: str) -> tuple[Any, Any]:
    try:
        return resolve_paper_legacy_import_access(current_user, legacy_account_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "LEGACY_PAPER_IMPORT_ACCESS_DENIED", "message": "The requested import is not authorized."},
        ) from None


@router.get("/accounts/{legacy_account_id}")
async def inspect_legacy_paper_import(
    legacy_account_id: str,
    current_user: TokenPayload = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> dict[str, Any]:
    """Read the stable source inventory and exact configured Host receipt."""

    access, grant = _access(current_user, legacy_account_id)
    paper = grant.paper_binding
    try:
        inventory = await inspect_stable_legacy_paper_account(
            service, legacy_account_id, current_user.sub
        )
        source_receipt = await get_legacy_paper_import_receipt(
            legacy_account_id, current_user.sub
        )
        target = await inspect_legacy_paper_import_target(
            legacy_account_id, access.worker, scope=paper.execution_scope
        )
        target_receipt = target["source_receipt"]
        if target_receipt is not None and (
            target_receipt["source_account_id"] != legacy_account_id
            or target_receipt["source_owner_id"] != current_user.sub
        ):
            raise LegacyPaperImportError("TARGET_IMPORT_BINDING_MISMATCH")
    except LegacyPaperImportError as error:
        raise _http_error(error.code) from None
    except LegacyPaperInventoryError as error:
        raise _http_error(error.code, inventory=True) from None
    except ServiceReadUnavailableError:
        raise _http_error("TARGET_IMPORT_UNAVAILABLE") from None
    except Exception:
        raise _http_error("LEGACY_IMPORT_UNAVAILABLE") from None
    return {
        "source_inventory": {
            "complete": inventory.complete,
            "sha256": inventory.digest,
            "order_count": inventory.order_count,
            "position_count": inventory.position_count,
            "trade_count": inventory.trade_count,
            "reasons": list(inventory.reasons),
            "authority": "read-only legacy Paper source snapshot",
        },
        "source_receipt": _receipt_payload(source_receipt),
        "target": target,
    }


@router.post("/accounts/{legacy_account_id}/migrate")
async def migrate_legacy_paper_import(
    legacy_account_id: str,
    request: _ConfirmRequest,
    current_user: TokenPayload = Depends(get_current_user),
    service: PaperTradingService = Depends(get_paper_trading_service),
) -> dict[str, Any]:
    """Freeze, import, and verify one explicitly confirmed owner-bound ledger."""

    del request  # Pydantic has already required an explicit true confirmation.
    access, grant = _access(current_user, legacy_account_id)
    paper = grant.paper_binding
    try:
        result = await migrate_nonempty_legacy_paper_account(
            service,
            current_user.sub,
            paper,
            target_worker=access.worker,
            scope=paper.execution_scope,
            domain=paper.paper_owner_domain,
            symbol_bindings=grant.symbol_bindings,
        )
    except LegacyPaperImportError as error:
        raise _http_error(error.code) from None
    except LegacyPaperInventoryError as error:
        raise _http_error(error.code, inventory=True) from None
    except ServiceReadUnavailableError:
        raise _http_error("TARGET_IMPORT_UNAVAILABLE") from None
    except Exception:
        raise _http_error("LEGACY_IMPORT_UNAVAILABLE") from None
    return {
        "receipt": _receipt_payload(result.receipt),
        "legacy_ledger_retained_read_only": result.legacy_ledger_retained_read_only,
        "imported_rows_are_exchange_facts": result.imported_rows_are_exchange_facts,
        "old_rules_approvals_alerts_activated": result.old_rules_approvals_alerts_activated,
    }


@router.post("/accounts/{legacy_account_id}/rollback")
async def rollback_legacy_paper_import_receipt(
    legacy_account_id: str,
    request: _RollbackRequest,
    current_user: TokenPayload = Depends(get_current_user),
) -> dict[str, Any]:
    """Abort only the exact non-active prepared import named by its digest."""

    access, grant = _access(current_user, legacy_account_id)
    try:
        receipt = await rollback_legacy_paper_import(
            legacy_account_id,
            current_user.sub,
            source_inventory_sha256=request.source_inventory_sha256,
            target_worker=access.worker,
            scope=grant.paper_binding.execution_scope,
        )
    except LegacyPaperImportError as error:
        raise _http_error(error.code) from None
    except ServiceReadUnavailableError:
        raise _http_error("TARGET_IMPORT_UNAVAILABLE") from None
    except Exception:
        raise _http_error("LEGACY_IMPORT_UNAVAILABLE") from None
    return {"receipt": _receipt_payload(receipt)}


__all__ = ["router"]
