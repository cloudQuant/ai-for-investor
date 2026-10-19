"""Stop one trusted service-managed strategy run through its owner fence.

The stop-new owner receipt, open-order disposition, strategy process exit, and
subscription cleanup are separate facts.  This module never cancels orders,
closes positions, or signals an arbitrary PID.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.services.live_trading import manager as manager_module
from app.services.live_trading.service_execution_launch import (
    ServiceStrategyProfileError,
    get_service_strategy_profile_registry,
)
from app.services.monitoring_control import OwnerControlError

_MANAGED_FIELD = "_server_service_execution_managed"
_PROFILE_FIELD = "_server_service_execution_profile_ref"
_RUN_FIELD = "_server_service_execution_run_id"
_STOP_NEW_REF_RE = re.compile(r"^strategy-stop-new-v1:[0-9a-f]{64}$")
_COMMAND_ID_RE = re.compile(r"^afi-monitor-stop-new-v1-[0-9a-f]{32}$")
_SAFE_ERROR_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_OPEN_ORDER_POLICY = "leave_open_and_report"


class StrategyProcessStopError(ValueError):
    """Finite error code for a service-strategy stop request."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StrategyProcessStopReceipt:
    """Finite facts from one exact strategy-run stop attempt."""

    status: Literal["stopped", "partial", "unknown"]
    instance_id: str
    profile_ref: str
    account_ref: str
    strategy_ref: str
    run_id: str
    stop_new_status: Literal[
        "acknowledged", "rejected", "pending", "claimed", "expired", "unknown"
    ]
    stop_new_command_id: str | None
    stop_new_owner_final: bool
    stop_new_reconciliation_required: bool
    stop_new_effect: Literal["fenced", "already_fenced"] | None
    process_status: Literal["stopped", "running", "unknown"]
    process_exit_code: int | None
    subscription_status: Literal["released", "retained", "unknown"]
    open_order_policy: Literal["leave_open_and_report"]
    open_orders_status: Literal["left_open_unverified", "not_reached"]
    positions_status: Literal["unobserved"]
    error_code: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Return a JSON-safe receipt without raw exceptions or owner payloads."""

        return asdict(self)


async def stop_service_strategy_process(
    manager: Any,
    owner_control_deployment: Any,
    *,
    subject: str,
    instance_id: str,
    binding: Any,
    idempotency_key: str,
    open_order_policy: str,
) -> StrategyProcessStopReceipt:
    """Fence new owner writes, then gracefully stop the exact child run.

    ``binding`` must be the identity-selected STOP_NEW grant from the trusted
    owner-control deployment.  The only order policy implemented here is to
    leave open orders unchanged and report them as unverified.  A caller that
    needs cancellation must use its separate exact CANCEL grant before asking
    this function to release the strategy process.
    """

    if open_order_policy != _OPEN_ORDER_POLICY:
        raise StrategyProcessStopError("ORDER_POLICY_UNSUPPORTED")
    _validate_request_text(subject, instance_id, idempotency_key)
    profile, run_id, process = _resolve_exact_run(
        manager,
        owner_control_deployment,
        subject=subject,
        instance_id=instance_id,
        binding=binding,
    )

    try:
        projection = await asyncio.to_thread(
            owner_control_deployment.submit_control,
            binding,
            action="STOP_NEW",
            subject=subject,
            alert_id=_strategy_stop_correlation(instance_id, run_id),
            idempotency_key=idempotency_key,
        )
        stop_new = _project_stop_new(projection)
    except OwnerControlError as exc:
        stop_new = _unknown_stop_new(_safe_error_code(exc.code))
    except Exception:
        stop_new = _unknown_stop_new("OWNER_CONTROL_UNAVAILABLE")

    if stop_new["status"] != "acknowledged":
        terminal = stop_new["status"] in {"rejected", "expired"}
        process_state, exit_code = _process_state(process)
        return _receipt(
            status="partial" if terminal else "unknown",
            profile=profile,
            instance_id=instance_id,
            run_id=run_id,
            stop_new=stop_new,
            process_status=process_state,
            process_exit_code=exit_code,
            subscription_status="retained" if process_state == "running" else "unknown",
            open_orders_status="not_reached",
            error_code=stop_new.get("error_code"),
        )

    try:
        result = await manager.stop_instance(
            instance_id,
            user_id=subject,
            expected_service_execution_profile_ref=profile.profile_ref,
            expected_service_execution_run_id=run_id,
            expected_service_execution_process=process,
        )
    except Exception as exc:
        process_state, exit_code = _process_state(process)
        code = _manager_error_code(exc)
        return _receipt(
            status="unknown",
            profile=profile,
            instance_id=instance_id,
            run_id=run_id,
            stop_new=stop_new,
            process_status=process_state,
            process_exit_code=exit_code,
            subscription_status="unknown",
            open_orders_status="left_open_unverified",
            error_code=code,
        )

    process_state, exit_code = _process_state(process)
    if (
        not isinstance(result, Mapping)
        or result.get("status") != "stopped"
        or type(exit_code) is not int
        or exit_code != 0
    ):
        return _receipt(
            status="unknown",
            profile=profile,
            instance_id=instance_id,
            run_id=run_id,
            stop_new=stop_new,
            process_status="unknown" if process_state != "running" else process_state,
            process_exit_code=exit_code,
            subscription_status="unknown",
            open_orders_status="left_open_unverified",
            error_code="PROCESS_EXIT_UNCONFIRMED",
        )

    # The service runner exits zero only after ServiceExecutionSession closes
    # its runtime with no unregister uncertainty. This says nothing about
    # exchange orders or account positions, which are deliberately unobserved.
    return _receipt(
        status="stopped",
        profile=profile,
        instance_id=instance_id,
        run_id=run_id,
        stop_new=stop_new,
        process_status="stopped",
        process_exit_code=exit_code,
        subscription_status="released",
        open_orders_status="left_open_unverified",
    )


def select_stop_new_binding(
    manager: Any,
    owner_control_deployment: Any,
    *,
    subject: str,
    instance_id: str,
) -> Any:
    """Select the unique trusted STOP_NEW grant for the current exact run.

    The HTTP caller chooses only the owned instance ID.  Account, strategy,
    run, and operator grant are derived from the manager-owned process and
    installed service-strategy profile.  A deployment with multiple grants
    for the same exact run is ambiguous and is rejected instead of asking the
    browser to choose an authorization scope.
    """

    profile, run_id, _process = _resolve_current_service_run(
        manager, subject=subject, instance_id=instance_id
    )
    bindings = getattr(owner_control_deployment, "bindings", None)
    if not isinstance(bindings, (tuple, list)):
        raise StrategyProcessStopError("OWNER_CONTROL_BINDING_INVALID")

    matches: list[Any] = []
    expected_scope_label = f"strategy:{profile.strategy_ref}:{run_id}:stop_new"
    for binding in bindings:
        config = getattr(binding, "config", None)
        allowed_actions = getattr(config, "allowed_actions", None)
        wire_scope = getattr(binding, "wire_scope", None)
        if (
            getattr(config, "subject", None) == subject
            and isinstance(allowed_actions, (tuple, list))
            and "STOP_NEW" in allowed_actions
            and getattr(config, "wire_account_ref", None) == profile.account_ref
            and getattr(config, "command_scope", None) == expected_scope_label
            and getattr(wire_scope, "account_ref", None) == profile.account_ref
            and getattr(wire_scope, "strategy_ref", None) == profile.strategy_ref
            and getattr(wire_scope, "run_id", None) == run_id
        ):
            matches.append(binding)

    if not matches:
        raise StrategyProcessStopError("OWNER_CONTROL_NOT_AUTHORIZED")
    if len(matches) != 1:
        raise StrategyProcessStopError("OWNER_CONTROL_BINDING_AMBIGUOUS")
    return matches[0]


def _resolve_exact_run(
    manager: Any,
    owner_control_deployment: Any,
    *,
    subject: str,
    instance_id: str,
    binding: Any,
) -> tuple[Any, str, Any]:
    bindings = getattr(owner_control_deployment, "bindings", None)
    if not isinstance(bindings, (tuple, list)) or not any(
        candidate is binding for candidate in bindings
    ):
        raise StrategyProcessStopError("OWNER_CONTROL_BINDING_INVALID")
    config = getattr(binding, "config", None)
    allowed_actions = getattr(config, "allowed_actions", None)
    if (
        getattr(config, "subject", None) != subject
        or not isinstance(allowed_actions, (tuple, list))
        or "STOP_NEW" not in allowed_actions
    ):
        raise StrategyProcessStopError("OWNER_CONTROL_NOT_AUTHORIZED")

    profile, run_id, process = _resolve_current_service_run(
        manager, subject=subject, instance_id=instance_id
    )
    expected_scope_label = f"strategy:{profile.strategy_ref}:{run_id}:stop_new"
    if (
        getattr(config, "wire_account_ref", None) != profile.account_ref
        or getattr(config, "command_scope", None) != expected_scope_label
    ):
        raise StrategyProcessStopError("SERVICE_STRATEGY_SCOPE_MISMATCH")

    wire_scope = getattr(binding, "wire_scope", None)
    if (
        getattr(wire_scope, "account_ref", None) != profile.account_ref
        or getattr(wire_scope, "strategy_ref", None) != profile.strategy_ref
        or getattr(wire_scope, "run_id", None) != run_id
    ):
        raise StrategyProcessStopError("OWNER_CONTROL_RUN_MISMATCH")
    return profile, run_id, process


def _resolve_current_service_run(
    manager: Any, *, subject: str, instance_id: str
) -> tuple[Any, str, Any]:
    with manager_module._instance_store_lock():
        instance = manager_module._load_instances().get(instance_id)
        process = getattr(manager, "_processes", {}).get(instance_id)
        if not isinstance(instance, dict) or instance.get("user_id") != subject:
            raise StrategyProcessStopError("INSTANCE_NOT_FOUND")
        profile_ref = instance.get(_PROFILE_FIELD)
        run_id = instance.get(_RUN_FIELD)
        strategy_id = instance.get("strategy_id")
        if (
            instance.get(_MANAGED_FIELD) is not True
            or str(instance.get("_server_execution_mode") or "live") != "live"
            or instance.get("status") not in {"running", "error"}
            or type(profile_ref) is not str
            or not profile_ref
            or type(run_id) is not str
            or not run_id
            or type(strategy_id) is not str
            or not strategy_id
            or not _is_utf8_text(profile_ref, max_bytes=128)
            or not _is_utf8_text(run_id, max_bytes=128)
            or not _is_utf8_text(strategy_id, max_bytes=128)
            or process is None
            or getattr(process, "_bt_service_execution", False) is not True
            or getattr(process, "returncode", None) is not None
            or type(getattr(process, "pid", None)) is not int
            or type(instance.get("pid")) is not int
            or instance.get("pid") != process.pid
        ):
            raise StrategyProcessStopError("SERVICE_STRATEGY_RUN_UNAVAILABLE")

    try:
        registry = get_service_strategy_profile_registry({profile_ref})
        profile = registry.resolve(profile_ref)
    except ServiceStrategyProfileError as exc:
        raise StrategyProcessStopError(_safe_error_code(exc.code)) from None
    if profile.strategy_id != strategy_id or subject not in profile.authorized_subjects:
        raise StrategyProcessStopError("SERVICE_STRATEGY_SCOPE_MISMATCH")
    return profile, run_id, process


def _project_stop_new(value: object) -> dict[str, Any]:
    projection_fields = {
        "command_id",
        "status",
        "outcome",
        "effect_ref",
        "effect_result",
        "request_recorded",
        "owner_final",
        "reconciliation_required",
    }
    envelope_fields = projection_fields | {"action", "deployment_version"}
    if (
        not isinstance(value, Mapping)
        or set(value) != envelope_fields
        or value.get("action") != "stop_new"
        or type(value.get("deployment_version")) is not str
        or not value["deployment_version"]
        or value["deployment_version"] != value["deployment_version"].strip()
        or len(value["deployment_version"]) > 64
        or not value["deployment_version"].isprintable()
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    value = {name: value[name] for name in projection_fields}
    command_id = value.get("command_id")
    status = value.get("status")
    owner_final = value.get("owner_final")
    reconciliation = value.get("reconciliation_required")
    if (
        type(command_id) is not str
        or _COMMAND_ID_RE.fullmatch(command_id) is None
        or value.get("request_recorded") is not True
        or status not in {"pending", "claimed", "acknowledged", "rejected", "expired", "unknown"}
        or type(owner_final) is not bool
        or type(reconciliation) is not bool
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    effect = value.get("effect_result")
    effect_ref = value.get("effect_ref")
    outcome = value.get("outcome")
    effect_result: str | None = None
    if status == "acknowledged":
        if (
            owner_final is not True
            or outcome != "applied"
            or reconciliation is not False
            or not isinstance(effect, Mapping)
            or set(effect) != {"action", "result"}
            or effect.get("action") != "stop_new"
            or effect.get("result") not in {"fenced", "already_fenced"}
            or type(effect_ref) is not str
            or _STOP_NEW_REF_RE.fullmatch(effect_ref) is None
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
        effect_result = effect["result"]
    elif status in {"pending", "claimed", "unknown"}:
        expected_reconciliation = status in {"claimed", "unknown"}
        expected_outcome = "unknown" if status == "unknown" else None
        if (
            owner_final is not False
            or outcome != expected_outcome
            or effect is not None
            or effect_ref is not None
            or reconciliation is not expected_reconciliation
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    elif status == "rejected":
        if (
            owner_final is not True
            or outcome != "rejected"
            or reconciliation is not False
            or effect_ref is not None
            or not isinstance(effect, Mapping)
            or set(effect) != {"action", "result"}
            or effect.get("action") != "stop_new"
            or effect.get("result") not in {"run_not_active", "migration_write_disabled"}
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    else:  # expired is a final issuer decision, not an owner-applied fence.
        if (
            owner_final is not False
            or outcome is not None
            or reconciliation is not False
            or effect is not None
            or effect_ref is not None
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    return {
        "status": status,
        "command_id": command_id,
        "owner_final": owner_final,
        "reconciliation_required": reconciliation,
        "effect": effect_result,
    }


def _unknown_stop_new(error_code: str) -> dict[str, Any]:
    return {
        "status": "unknown",
        "command_id": None,
        "owner_final": False,
        "reconciliation_required": True,
        "effect": None,
        "error_code": error_code,
    }


def _receipt(
    *,
    status: Literal["stopped", "partial", "unknown"],
    profile: Any,
    instance_id: str,
    run_id: str,
    stop_new: Mapping[str, Any],
    process_status: Literal["stopped", "running", "unknown"],
    process_exit_code: int | None,
    subscription_status: Literal["released", "retained", "unknown"],
    open_orders_status: Literal["left_open_unverified", "not_reached"],
    error_code: str | None = None,
) -> StrategyProcessStopReceipt:
    raw_error = error_code or stop_new.get("error_code")
    safe_error = _safe_error_code(raw_error) if raw_error is not None else None
    return StrategyProcessStopReceipt(
        status=status,
        instance_id=instance_id,
        profile_ref=profile.profile_ref,
        account_ref=profile.account_ref,
        strategy_ref=profile.strategy_ref,
        run_id=run_id,
        stop_new_status=stop_new["status"],
        stop_new_command_id=stop_new["command_id"],
        stop_new_owner_final=stop_new["owner_final"],
        stop_new_reconciliation_required=stop_new["reconciliation_required"],
        stop_new_effect=stop_new["effect"],
        process_status=process_status,
        process_exit_code=process_exit_code,
        subscription_status=subscription_status,
        open_order_policy=_OPEN_ORDER_POLICY,
        open_orders_status=open_orders_status,
        positions_status="unobserved",
        error_code=safe_error,
    )


def _process_state(process: Any) -> tuple[Literal["running", "unknown"], int | None]:
    exit_code = getattr(process, "returncode", None)
    if exit_code is None:
        return "running", None
    return "unknown", exit_code if type(exit_code) is int else None


def _strategy_stop_correlation(instance_id: str, run_id: str) -> str:
    digest = hashlib.sha256(f"{instance_id}\0{run_id}".encode()).hexdigest()
    return f"strategy-stop:{digest}"


def _validate_request_text(subject: str, instance_id: str, idempotency_key: str) -> None:
    if (
        type(subject) is not str
        or not subject
        or subject != subject.strip()
        or len(subject) > 256
        or not _is_utf8_text(subject, max_bytes=256)
        or type(instance_id) is not str
        or not instance_id
        or instance_id != instance_id.strip()
        or len(instance_id) > 128
        or not _is_utf8_text(instance_id, max_bytes=128)
        or type(idempotency_key) is not str
        or not idempotency_key
        or idempotency_key != idempotency_key.strip()
        or not _is_utf8_text(idempotency_key, max_bytes=256)
    ):
        raise StrategyProcessStopError("STOP_REQUEST_INVALID")


def _is_utf8_text(value: str, *, max_bytes: int) -> bool:
    try:
        return len(value.encode("utf-8", errors="strict")) <= max_bytes
    except UnicodeEncodeError:
        return False


def _safe_error_code(value: object) -> str:
    if type(value) is str and _SAFE_ERROR_RE.fullmatch(value):
        return value
    return "STOP_OPERATION_UNCERTAIN"


def _manager_error_code(exc: Exception) -> str:
    known = {
        "SERVICE_EXECUTION_RUN_IDENTITY_CHANGED",
        "SERVICE_EXECUTION_STOP_CONTROL_UNAVAILABLE",
        "SERVICE_EXECUTION_CLOSE_UNCERTAIN",
    }
    value = getattr(exc, "code", None)
    if type(value) is not str:
        value = str(exc)
    return value if value in known else "PROCESS_STOP_UNCERTAIN"
