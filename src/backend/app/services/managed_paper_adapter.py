"""Application adapter for the existing SDK managed-paper owner.

The adapter resolves only a server-configured paper binding through the
authenticated service-read directory.  It creates no SDK runtime, does not
fall back to the legacy matcher, and projects status only from the durable
managed order journal.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.ai_trading import OrderType as AIOrderType
from app.schemas.ai_trading import TradeAction, TradingIntent
from app.schemas.paper_trading import OrderRequest
from app.services.legacy_paper_migration import (
    LegacyPaperInventoryError,
    assess_empty_account_cutover,
    inspect_stable_legacy_paper_account,
    require_active_paper_cutover_receipt,
)

logger = logging.getLogger(__name__)

_MAX_OPERATION_KEY_LENGTH = 256
_SUPPORTED_EXECUTION_STATES = frozenset(
    {
        "PENDING_ADMISSION",
        "PENDING_DISPATCH",
        "DISPATCHING",
        "ACKED",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "BLOCKED",
        "UNKNOWN",
    }
)


class ManagedPaperOrderError(RuntimeError):
    """A finite, safe error at the managed-paper application boundary."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int = 409,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status_code = status_code
        self.details = dict(details or {})
        super().__init__(code)


class ManagedPaperOrderAdapter:
    """Submit and query one managed paper owner on the existing owner worker."""

    def __init__(
        self,
        *,
        legacy_service_factory: Callable[[], Any] | None = None,
        access_resolver: Callable[[str, str], Any] | None = None,
    ) -> None:
        self._legacy_service_factory = legacy_service_factory
        self._access_resolver = access_resolver

    async def submit_manual(
        self,
        *,
        subject: str,
        request: OrderRequest,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if request.order_type != "market" or any(
            value is not None for value in (request.price, request.stop_price, request.limit_price)
        ):
            raise ManagedPaperOrderError("UNSUPPORTED_PAPER_ORDER_TYPE", status_code=422)
        if request.side not in {"buy", "sell"}:
            raise ManagedPaperOrderError("UNSUPPORTED_PAPER_SIDE", status_code=422)
        side = "BUY" if request.side == "buy" else "SELL"
        effect = "OPEN" if side == "BUY" else "CLOSE"
        return await self._submit(
            subject=subject,
            legacy_account_id=request.account_id,
            instrument=request.symbol,
            quantity=request.size,
            side=side,
            position_effect=effect,
            reduce_only=effect == "CLOSE",
            operation_key=idempotency_key,
            operation_source="manual",
            display_order_type="market",
        )

    async def submit_ai(
        self,
        *,
        subject: str,
        legacy_account_id: str | None,
        intent: TradingIntent,
        trade_id: str,
    ) -> dict[str, Any]:
        if not legacy_account_id:
            raise ManagedPaperOrderError("PAPER_ACCOUNT_REQUIRED", status_code=422)
        if intent.order_type is not AIOrderType.MARKET:
            raise ManagedPaperOrderError("UNSUPPORTED_PAPER_ORDER_TYPE", status_code=422)
        if any(value is not None for value in (intent.price, intent.stop_loss, intent.take_profit)):
            raise ManagedPaperOrderError(
                "UNSUPPORTED_PAPER_PRICE_CONDITION",
                status_code=422,
            )
        if intent.action is TradeAction.BUY:
            side, effect, reduce_only = "BUY", "OPEN", False
        elif intent.action is TradeAction.CLOSE:
            # This SDK paper model currently supports long close only.  It
            # rejects short-open and never maps CLOSE to an OPEN order.
            side, effect, reduce_only = "SELL", "CLOSE", True
        else:
            raise ManagedPaperOrderError(
                "UNSUPPORTED_PAPER_ACTION",
                status_code=422,
                details={"action": intent.action.value},
            )
        return await self._submit(
            subject=subject,
            legacy_account_id=legacy_account_id,
            instrument=intent.symbol or "",
            quantity=intent.quantity,
            side=side,
            position_effect=effect,
            reduce_only=reduce_only,
            operation_key=trade_id,
            operation_source="ai",
            display_order_type="market",
        )

    async def read_order(
        self,
        *,
        subject: str,
        legacy_account_id: str,
        intent_id: str,
    ) -> dict[str, Any]:
        access, binding, worker = self._resolve_access(subject, legacy_account_id)
        import_binding = _paper_import_binding(
            access, subject=subject, legacy_account_id=legacy_account_id, paper_binding=binding
        )
        try:
            await require_active_paper_cutover_receipt(
                legacy_account_id,
                subject,
                binding,
                service_factory=self._legacy_service,
                import_binding=import_binding,
                target_worker=worker,
            )
        except LegacyPaperInventoryError as error:
            raise _cutover_error(error) from None
        if not _managed_intent_id(intent_id):
            raise ManagedPaperOrderError("INVALID_INTENT_ID", status_code=422)
        query_scope_ref = _binding_value(binding, "query_scope_ref")
        if not _identifier(query_scope_ref):
            raise ManagedPaperOrderError("PAPER_QUERY_NOT_CONFIGURED", status_code=503)
        try:
            view = await worker.read_order(query_scope_ref, intent_id)
        except Exception as error:
            raise ManagedPaperOrderError(
                _safe_code(error), status_code=503
            ) from None
        _require_view_identity(view, intent_id)
        return _project_managed_view(
            view,
            intent_id=intent_id,
            legacy_account_id=legacy_account_id,
            instrument=None,
            side=None,
            position_effect=None,
            order_type="market",
            requested_quantity=None,
        )

    async def prepare_cutover(
        self,
        *,
        subject: str,
        legacy_account_id: str,
    ) -> dict[str, Any]:
        """Explicitly qualify the verified empty or imported source for managed use."""

        access, binding, worker = self._resolve_access(subject, legacy_account_id)
        import_binding = _paper_import_binding(
            access, subject=subject, legacy_account_id=legacy_account_id, paper_binding=binding
        )
        try:
            from app.services.legacy_paper_import_migration import (
                prepare_managed_paper_cutover,
            )

            receipt = await prepare_managed_paper_cutover(
                self._legacy_service(),
                subject,
                binding,
                import_binding,
                target_worker=worker,
            )
        except LegacyPaperInventoryError as error:
            raise _cutover_error(error) from None
        return {
            "receipt_id": receipt.id,
            "account_id": receipt.legacy_account_id,
            "state": receipt.state,
            "receipt_version": receipt.receipt_version,
            "source_inventory_sha256": receipt.source_inventory_sha256,
            "binding_sha256": receipt.binding_sha256,
            "paper_domain_sha256": receipt.paper_domain_sha256,
            "source_counts": {
                "orders": receipt.source_order_count,
                "positions": receipt.source_position_count,
                "trades": receipt.source_trade_count,
            },
            "legacy_ledger_retained_read_only": True,
            "data_migrated": False,
            "source": "managed_paper",
        }

    async def _submit(
        self,
        *,
        subject: str,
        legacy_account_id: str,
        instrument: str,
        quantity: Any,
        side: str,
        position_effect: str,
        reduce_only: bool,
        operation_key: str,
        operation_source: str,
        display_order_type: str,
    ) -> dict[str, Any]:
        if not _identifier(subject) or not _identifier(legacy_account_id):
            raise ManagedPaperOrderError("INVALID_SELECTOR", status_code=422)
        if not _operation_key(operation_key):
            raise ManagedPaperOrderError("INVALID_IDEMPOTENCY_KEY", status_code=422)
        normalized_instrument = instrument.strip().upper() if type(instrument) is str else ""
        if not normalized_instrument:
            raise ManagedPaperOrderError("INVALID_INSTRUMENT", status_code=422)
        normalized_quantity = _positive_decimal(quantity)
        if normalized_quantity is None:
            raise ManagedPaperOrderError("INVALID_QUANTITY", status_code=422)

        access, binding, worker = self._resolve_access(subject, legacy_account_id)
        import_binding = _paper_import_binding(
            access, subject=subject, legacy_account_id=legacy_account_id, paper_binding=binding
        )
        legacy_service = self._legacy_service()
        try:
            receipt = await require_active_paper_cutover_receipt(
                legacy_account_id,
                subject,
                binding,
                service_factory=lambda: legacy_service,
                import_binding=import_binding,
                target_worker=worker,
            )
            source_kind = getattr(receipt, "source_kind", "empty_account")
            if source_kind == "empty_account":
                inventory = await inspect_stable_legacy_paper_account(
                    legacy_service, legacy_account_id, subject
                )
                assessment = assess_empty_account_cutover(inventory, binding)
                if not assessment.ready:
                    raise ManagedPaperOrderError(
                        "LEGACY_PAPER_CUTOVER_NOT_READY",
                        status_code=409,
                        details={
                            "source": "legacy",
                            "inventory_sha256": assessment.inventory_sha256,
                            "order_count": assessment.order_count,
                            "position_count": assessment.position_count,
                            "trade_count": assessment.trade_count,
                            "reasons": list(assessment.reasons),
                        },
                    )
                if inventory.digest != receipt.source_inventory_sha256:
                    raise ManagedPaperOrderError(
                        "MANAGED_PAPER_LEGACY_INVENTORY_CHANGED",
                        status_code=409,
                        details={"source": "legacy", "receipt_id": receipt.id},
                    )
            elif source_kind == "imported_legacy":
                # Imported source rows are retained read-only and already
                # independently verified with the persisted AFI12/E handoff.
                # The legacy service remains fail-closed; only the configured
                # managed owner can receive the next order.
                pass
            else:
                raise LegacyPaperInventoryError("MANAGED_PAPER_CUTOVER_BINDING_MISMATCH")
        except LegacyPaperInventoryError as error:
            raise _cutover_error(error) from None

        metadata_versions = _binding_value(binding, "instrument_metadata_versions")
        if not isinstance(metadata_versions, Mapping):
            raise ManagedPaperOrderError("PAPER_INSTRUMENTS_NOT_CONFIGURED", status_code=503)
        metadata_version = metadata_versions.get(normalized_instrument)
        if not _identifier(metadata_version):
            raise ManagedPaperOrderError("PAPER_INSTRUMENT_NOT_CONFIGURED", status_code=422)

        intent_id = _stable_intent_id(
            operation_source, subject, legacy_account_id, operation_key
        )
        arguments = {
            "intent_id": intent_id,
            "signal_id": intent_id,
            "instrument": normalized_instrument,
            "side": side,
            "position_effect": position_effect,
            "order_type": "MARKET",
            "quantity": format(normalized_quantity, "f"),
            "price": None,
            "time_in_force": "FOK",
            "reduce_only": reduce_only,
            "metadata_version": metadata_version,
            "deadline_ns": None,
            "tags": {"afi_source": operation_source},
        }

        submit_error: str | None = None
        submission_acknowledged = False
        try:
            reply = await worker.submit_paper_order(
                _binding_value(binding, "scope_ref"), arguments
            )
        except Exception as error:
            # The call may have crossed the process boundary.  Query this same
            # stable intent exactly once; never resubmit with a new identifier.
            submit_error = _safe_code(error)
        else:
            if (
                isinstance(reply, Mapping)
                and reply.get("ok") is True
                and reply.get("code") == "OK"
            ):
                submission_acknowledged = True
            else:
                code = reply.get("code") if isinstance(reply, Mapping) else None
                submit_error = (
                    code[:64]
                    if type(code) is str and code and code.replace("_", "").isalnum()
                    else "INVALID_SUBMIT_REPLY"
                )

        query_scope_ref = _binding_value(binding, "query_scope_ref")
        if not _identifier(query_scope_ref):
            raise ManagedPaperOrderError("PAPER_QUERY_NOT_CONFIGURED", status_code=503)
        try:
            view = await worker.read_order(query_scope_ref, intent_id)
        except Exception as error:
            details = {"intent_id": intent_id}
            if submit_error:
                details["submit_code"] = submit_error
            details["query_code"] = _safe_code(error)
            raise ManagedPaperOrderError(
                "MANAGED_ORDER_STATE_UNAVAILABLE", status_code=503, details=details
            ) from None
        _require_view_identity(view, intent_id)

        result = _project_managed_view(
            view,
            intent_id=intent_id,
            legacy_account_id=legacy_account_id,
            instrument=normalized_instrument,
            side=side,
            position_effect=position_effect,
            order_type=display_order_type,
            requested_quantity=normalized_quantity,
        )
        if submit_error is not None:
            result["submit_code"] = submit_error
            if submit_error == "INTENT_CONFLICT":
                raise ManagedPaperOrderError(
                    "PAPER_IDEMPOTENCY_CONFLICT",
                    status_code=409,
                    details={"intent_id": intent_id, "observed_state": result["state"]},
                )
        result["submission_acknowledged"] = submission_acknowledged
        result["source"] = "managed_paper"
        return result

    def _resolve_access(self, subject: str, legacy_account_id: str) -> tuple[Any, Any, Any]:
        resolver = self._access_resolver
        if resolver is None:
            try:
                from app.api.service_read import resolve_paper_submit_access
            except ImportError:
                raise ManagedPaperOrderError(
                    "PAPER_SERVICE_NOT_CONFIGURED", status_code=503
                ) from None
            resolver = resolve_paper_submit_access
        try:
            resolved = resolver(subject, legacy_account_id)
        except ManagedPaperOrderError:
            raise
        except Exception as error:
            code = _safe_code(error)
            detail = getattr(error, "detail", None)
            if isinstance(detail, Mapping) and _safe_public_code(detail.get("code")):
                code = detail["code"]
            status_code = getattr(error, "status_code", 403)
            if type(status_code) is not int or status_code not in {403, 503}:
                status_code = 403
            raise ManagedPaperOrderError(code, status_code=status_code) from None
        if not isinstance(resolved, tuple) or len(resolved) != 2:
            raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503)
        access, binding = resolved
        bindings = getattr(access, "paper_submit_bindings", None)
        if not isinstance(bindings, Mapping) or bindings.get(legacy_account_id) is not binding:
            raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503)
        worker = getattr(access, "worker", None)
        if not callable(getattr(worker, "submit_paper_order", None)) or not callable(
            getattr(worker, "read_order", None)
        ):
            raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503)
        if (
            _binding_value(binding, "legacy_account_id") != legacy_account_id
            or not _identifier(_binding_value(binding, "scope_ref"))
            or not _identifier(_binding_value(binding, "account_ref"))
            or not _identifier(_binding_value(binding, "execution_domain_ref"))
            or not _identifier(_binding_value(binding, "strategy_ref"))
        ):
            raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503)
        return access, binding, worker

    def _legacy_service(self) -> Any:
        factory = self._legacy_service_factory
        if factory is None:
            from app.services.paper_trading_service import PaperTradingService

            factory = PaperTradingService
        return factory()


def _paper_import_binding(
    access: Any,
    *,
    subject: str,
    legacy_account_id: str,
    paper_binding: Any,
) -> Any | None:
    """Return only the separate server-configured import binding, if present."""

    bindings = getattr(access, "paper_legacy_import_bindings", None)
    if bindings is None:
        return None
    if not isinstance(bindings, Mapping):
        raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503)
    configured = bindings.get(legacy_account_id)
    if configured is None:
        return None
    try:
        from app.services.service_read.client import PaperLegacyImportBinding
    except ImportError:
        raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503) from None
    if (
        type(configured) is not PaperLegacyImportBinding
        or configured.owner_subject != subject
        or configured.legacy_account_id != legacy_account_id
        or configured.paper_binding is not paper_binding
        or configured.scope_ref != _binding_value(paper_binding, "scope_ref")
    ):
        raise ManagedPaperOrderError("PAPER_SERVICE_NOT_CONFIGURED", status_code=503)
    return configured


def _project_managed_view(
    view: Any,
    *,
    intent_id: str,
    legacy_account_id: str,
    instrument: str | None,
    side: str | None,
    position_effect: str | None,
    order_type: str,
    requested_quantity: Decimal | None,
) -> dict[str, Any]:
    quality = getattr(getattr(view, "quality", None), "value", None)
    state = getattr(view, "state", None)
    if quality in {"not_collected", "unavailable"} or not isinstance(state, str):
        state = "UNKNOWN"
    if state not in _SUPPORTED_EXECUTION_STATES:
        state = "UNKNOWN"
    status = _application_status(state)
    filled = getattr(view, "filled_quantity", None)
    average_price = getattr(view, "average_price", None)
    commission = getattr(view, "cumulative_commission", None)
    return {
        "id": intent_id,
        "intent_id": intent_id,
        "account_id": legacy_account_id,
        "symbol": instrument,
        "order_type": order_type,
        "side": side.lower() if side else None,
        "position_effect": position_effect,
        "size": float(requested_quantity) if requested_quantity is not None else None,
        "filled_size": _float_or_none(filled),
        "avg_fill_price": _float_or_none(average_price),
        "commission": _float_or_none(commission),
        "slippage": None,
        "status": status,
        "state": state,
        "state_quality": quality if quality in {"fresh", "stale"} else "unavailable",
        "is_terminal": getattr(view, "is_terminal", None),
        "unknown_reason": getattr(view, "unknown_reason", None),
        "review_required": getattr(view, "review_required", None),
        "updated_at_ns": getattr(view, "updated_at_ns", None),
        "detail_code": getattr(view, "detail_code", None),
        "source": "managed_paper",
    }


def _binding_value(binding: Any, name: str) -> Any:
    """Read a field from the typed binding or its mapping test projection."""
    if isinstance(binding, Mapping):
        return binding.get(name)
    return getattr(binding, name, None)


def _require_view_identity(view: Any, intent_id: str) -> None:
    """Never project a journal row whose typed identity differs from its key."""
    if getattr(view, "intent_id", None) != intent_id:
        raise ManagedPaperOrderError(
            "MANAGED_ORDER_STATE_IDENTITY_MISMATCH",
            status_code=503,
            details={"intent_id": intent_id},
        )


def _application_status(state: str) -> str:
    return {
        "PENDING_ADMISSION": "executing",
        "PENDING_DISPATCH": "executing",
        "DISPATCHING": "executing",
        "ACKED": "executing",
        "PARTIALLY_FILLED": "partial_filled",
        "FILLED": "filled",
        "CANCELLED": "cancelled",
        "REJECTED": "rejected",
        "BLOCKED": "blocked",
        "UNKNOWN": "unknown",
    }[state]


def _stable_intent_id(source: str, subject: str, account_id: str, operation_key: str) -> str:
    digest = hashlib.sha256(
        "\0".join(("afi-managed-paper-v1", source, subject, account_id, operation_key)).encode(
            "utf-8"
        )
    ).hexdigest()
    prefix = "afi-manual-" if source == "manual" else "afi-ai-"
    return prefix + digest


def _positive_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _operation_key(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value) <= _MAX_OPERATION_KEY_LENGTH
        and value.isprintable()
    )


def _managed_intent_id(value: object) -> bool:
    if type(value) is not str:
        return False
    prefix, separator, digest = value.partition("-")
    if not separator or prefix != "afi":
        return False
    source, separator, digest = digest.partition("-")
    return (
        separator == "-"
        and source in {"manual", "ai"}
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _identifier(value: Any) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value != "*"
        and len(value) <= 256
        and value.isprintable()
    )


def _safe_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if type(code) is str and code and code.replace("_", "").isalnum():
        return code[:64]
    return type(error).__name__[:64]


def _safe_public_code(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= 64
        and value.replace("_", "").isalnum()
    )


def _cutover_error(error: LegacyPaperInventoryError) -> ManagedPaperOrderError:
    status_code = 409
    if error.code in {"LEGACY_ACCOUNT_NOT_FOUND"}:
        status_code = 404
    elif error.code in {
        "LEGACY_PAPER_CUTOVER_STORE_UNAVAILABLE",
        "LEGACY_WRITE_FENCE_UNAVAILABLE",
        "LEGACY_WRITE_LEASE_RELEASE_UNAVAILABLE",
    }:
        status_code = 503
    elif error.code == "INVALID_SELECTOR":
        status_code = 422
    details = dict(error.details)
    if error.code == "LEGACY_PAPER_CUTOVER_NOT_READY":
        details.setdefault("source", "legacy")
    return ManagedPaperOrderError(error.code, status_code=status_code, details=details)


__all__ = ["ManagedPaperOrderAdapter", "ManagedPaperOrderError"]
