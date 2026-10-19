"""Same-host child-owned bridge to AFI's durable approved-target authority.

Import and call :func:`create_execution_approved_target_resources` only from
the trusted ``ServiceResourceProvider`` running on an explicitly protected
Execution ``account_owner`` Host thread. Ordinary AFI client deployments do
not import the Execution package or pass a callback/session across a process
boundary.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from app.services.strategy_approval_authority import StrategyOrderTargetCurrentStateProvider
from app.services.strategy_target_approvals import (
    ApprovedTargetOperationClaim,
    StrategyTargetApprovalError,
    consume_approved_target_v1,
    reserve_approved_target_operation,
    resolve_approved_target_v1,
)

_OPERATION_TIMEOUT_SECONDS = 5.0
_CANCELLATION_TIMEOUT_SECONDS = 2.0
_CLOSE_TIMEOUT_SECONDS = 5.0
_REQUIRED_TABLES = frozenset(
    {
        "strategy_target_approvals",
        "strategy_target_approval_events",
        "strategy_approval_authority_epochs",
        "strategy_order_approval_policy_heads",
        "strategy_order_approval_policy_versions",
        "strategy_versions",
        "strategy_branches",
        "strategies",
        "portfolio_composition_versions",
    }
)
_DEFINITE_CODES = frozenset(
    {
        "APPROVAL_NOT_FOUND",
        "APPROVAL_OWNER_BINDING_MISMATCH",
        "APPROVAL_IDENTITY_MISMATCH",
        "APPROVAL_SCOPE_MISMATCH",
        "APPROVAL_NOT_APPROVED",
        "APPROVAL_REVOKED",
        "APPROVAL_EXPIRED",
        "APPROVAL_VERSION_MISMATCH",
        "APPROVAL_TARGET_DIGEST_MISMATCH",
        "APPROVAL_TARGET_INVALID",
        "APPROVAL_POLICY_STALE",
        "APPROVAL_OPERATION_CONFLICT",
        "APPROVAL_CONSUMED_CONFLICT",
    }
)


class _ApprovedTargetStorePort:
    """Synchronous SDK port with one child-owned loop and per-call sessions."""

    def __init__(
        self,
        owner_bindings: Any,
        session_maker: Any,
        engine: Any,
        loop: asyncio.AbstractEventLoop,
    ):
        self._owner_bindings = owner_bindings
        self._session_maker = session_maker
        self._engine = engine
        self._loop = loop
        self._owner_thread = threading.get_ident()
        self._closed = False
        self._ready = False
        self._engine_disposed = False

    async def check_ready(self) -> None:
        async with self._session_maker() as session:
            await session.execute(text("SELECT 1"))
            connection = await session.connection()
            present = await connection.run_sync(
                lambda sync_connection: {
                    name for name in _REQUIRED_TABLES
                    if inspect(sync_connection).has_table(name)
                }
            )
            if present != _REQUIRED_TABLES:
                raise RuntimeError("APPROVAL_SCHEMA_UNAVAILABLE")
        self._ready = True

    def ready(self) -> bool:
        return (
            self._ready
            and not self._closed
            and threading.get_ident() == self._owner_thread
            and not self._loop.is_closed()
        )

    def reserve_approved_target_operation(self, **arguments: object) -> Mapping[str, object]:
        binding = self._require_binding(arguments)
        operation = self._with_session(
            reserve_approved_target_operation,
            self._store_arguments(arguments, binding),
        )
        if type(operation) is not ApprovedTargetOperationClaim:
            self._raise_ambiguous()
        return {
            "approval_ref": operation.approval_ref,
            "approval_version": operation.approval_version,
            "target_sha256": operation.target_sha256,
            "intent_id": operation.intent_id,
            "operation_request_sha256": operation.operation_request_sha256,
            "created": operation.created,
            "record_version": operation.record_version,
        }

    def resolve_approved_target_v1(self, **arguments: object) -> Mapping[str, object]:
        binding = self._require_binding(arguments)
        target = self._with_session(
            resolve_approved_target_v1,
            self._store_arguments(arguments, binding),
        )
        if not isinstance(target, Mapping):
            self._raise_ambiguous()
        return dict(target)

    def consume_approved_target_v1(self, **arguments: object) -> Mapping[str, object]:
        binding = self._require_binding(arguments)
        store_arguments = self._store_arguments(arguments, binding)
        store_arguments["intent_sha256"] = arguments.get("intent_sha256")
        store_arguments["current_state_provider"] = StrategyOrderTargetCurrentStateProvider()
        receipt = self._with_session(consume_approved_target_v1, store_arguments)
        if not isinstance(receipt, Mapping):
            self._raise_ambiguous()
        return dict(receipt)

    def close(self) -> None:
        self._require_owner()
        if self._closed:
            return
        if self._engine_disposed:
            self._loop.close()
            self._closed = True
            return
        try:
            self._drive(self._dispose_engine(), _CLOSE_TIMEOUT_SECONDS)
        except BaseException:
            # Keep the loop and engine attached so Host's owned-resource retry
            # can make another bounded close attempt on this same thread.
            raise
        self._engine_disposed = True
        self._loop.close()
        self._closed = True

    async def _dispose_engine(self) -> None:
        await self._engine.dispose()

    def _with_session(self, function: Any, arguments: dict[str, object]) -> Any:
        self._require_owner()
        if self._closed or not self._ready:
            self._raise_ambiguous()

        async def run() -> Any:
            async with self._session_maker() as session:
                return await function(session, **arguments)

        try:
            return self._drive(run(), _OPERATION_TIMEOUT_SECONDS)
        except StrategyTargetApprovalError as error:
            self._raise_typed(error)
        except BaseException as error:
            # SDK catches this exact package-owned exception type. Never map a
            # generic exception's .code to a denial after an uncertain commit.
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                raise
            self._raise_ambiguous()

    def _drive(self, awaitable: Any, timeout: float) -> Any:
        self._require_owner()
        if self._loop.is_closed() or self._loop.is_running():
            raise RuntimeError("APPROVAL_LOOP_UNAVAILABLE")
        task = self._loop.create_task(awaitable)
        done, pending = self._loop.run_until_complete(
            asyncio.wait((task,), timeout=timeout)
        )
        if pending:
            task.cancel()
            cancelled, still_pending = self._loop.run_until_complete(
                asyncio.wait((task,), timeout=_CANCELLATION_TIMEOUT_SECONDS)
            )
            if still_pending:
                raise TimeoutError("APPROVAL_TASK_CANCELLATION_UNCERTAIN")
            if task in cancelled:
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
            raise TimeoutError("APPROVAL_OPERATION_TIMEOUT")
        return task.result()

    def _require_binding(self, arguments: Mapping[str, object]) -> Any:
        self._require_owner()
        if not self.ready():
            self._raise_ambiguous()
        binding = self._owner_bindings.resolve(
            arguments.get("principal_ref"),
            arguments.get("identity"),
            arguments.get("wire_scope"),
        )
        if (
            binding is None
            or binding.owner_subject != arguments.get("owner_subject")
            or binding.expected_scope_ref != arguments.get("expected_scope_ref")
        ):
            from bt_api_execution.approved_target import ApprovedTargetAuthorityError

            raise ApprovedTargetAuthorityError("APPROVAL_OWNER_BINDING_MISMATCH")
        return binding

    @staticmethod
    def _store_arguments(arguments: Mapping[str, object], binding: Any) -> dict[str, object]:
        required = {
            "approval_ref",
            "approval_version",
            "target_sha256",
            "intent_id",
            "operation_key",
            "owner_subject",
            "principal_ref",
            "expected_scope_ref",
            "identity",
            "wire_scope",
        }
        if set(arguments) - (required | {"intent_sha256"}) or not required <= set(arguments):
            from bt_api_execution.approved_target import ApprovedTargetAuthorityError

            raise ApprovedTargetAuthorityError("APPROVAL_TARGET_INVALID")
        if (
            binding.owner_subject != arguments["owner_subject"]
            or binding.expected_scope_ref != arguments["expected_scope_ref"]
        ):
            from bt_api_execution.approved_target import ApprovedTargetAuthorityError

            raise ApprovedTargetAuthorityError("APPROVAL_OWNER_BINDING_MISMATCH")
        return {
            "approval_ref": arguments["approval_ref"],
            "approval_version": arguments["approval_version"],
            "target_sha256": arguments["target_sha256"],
            "operation_key": arguments["operation_key"],
            "intent_id": arguments["intent_id"],
            "owner_subject": binding.owner_subject,
            "principal_ref": binding.principal_ref,
            "expected_scope_ref": binding.expected_scope_ref,
            "identity": binding.identity,
            "wire_scope": binding.wire_scope,
        }

    def _raise_typed(self, error: StrategyTargetApprovalError) -> None:
        from bt_api_execution.approved_target import ApprovedTargetAuthorityError

        if (
            type(error) is StrategyTargetApprovalError
            and error.ambiguous is False
            and error.code in _DEFINITE_CODES
        ):
            raise ApprovedTargetAuthorityError(error.code) from None
        raise ApprovedTargetAuthorityError(
            "APPROVAL_CONSUME_OUTCOME_UNKNOWN", ambiguous=True
        ) from None

    def _raise_ambiguous(self) -> None:
        from bt_api_execution.approved_target import ApprovedTargetAuthorityError

        raise ApprovedTargetAuthorityError(
            "APPROVAL_CONSUME_OUTCOME_UNKNOWN", ambiguous=True
        ) from None

    def _require_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            from bt_api_execution.approved_target import ApprovedTargetAuthorityError

            raise ApprovedTargetAuthorityError("APPROVAL_CONSUME_OUTCOME_UNKNOWN", ambiguous=True)


def create_execution_approved_target_resources(
    *,
    owner_bindings: tuple[object, ...],
    protected_scopes: tuple[object, ...],
):
    """Create the explicitly selected, child-owned authority resource.

    ``owner_bindings`` and ``protected_scopes`` are immutable, code-owned SDK
    objects constructed by the trusted ServiceResourceProvider in the Host
    child. Database location always comes from this process's AFI settings; it
    is not a wire/client option.
    """

    if type(owner_bindings) is not tuple or not owner_bindings:
        raise RuntimeError("APPROVAL_OWNER_BINDINGS_REQUIRED")
    if type(protected_scopes) is not tuple or not protected_scopes:
        raise RuntimeError("APPROVAL_PROTECTED_SCOPES_REQUIRED")
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("APPROVAL_RUNNING_LOOP_UNSUPPORTED")

    from bt_api_execution.approved_target import (
        ApprovedTargetAuthorityV1,
        ApprovedTargetOwnerBindingsV1,
        ApprovedTargetOwnerBindingV1,
        ProtectedApprovedTargetScopesV1,
    )
    from bt_api_py.service_components import ComponentResources

    if any(type(item) is not ApprovedTargetOwnerBindingV1 for item in owner_bindings):
        raise RuntimeError("APPROVAL_OWNER_BINDING_CONFIG_INVALID")
    from bt_api_base.service_protocol import WireScope

    if any(type(item) is not WireScope for item in protected_scopes):
        raise RuntimeError("APPROVAL_PROTECTED_SCOPE_CONFIG_INVALID")

    bindings = ApprovedTargetOwnerBindingsV1(owner_bindings)
    scopes = ProtectedApprovedTargetScopesV1(protected_scopes)
    loop = asyncio.new_event_loop()
    engine = None
    bridge = None
    try:
        settings = get_settings()
        # The URL is read only inside the Host child from its trusted AFI
        # deployment environment; it is neither accepted as an argument nor
        # included in an exception/log representation.
        engine = create_async_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
            echo=False,
            pool_pre_ping=True,
        )
        maker = async_sessionmaker(engine, expire_on_commit=False)
        bridge = _ApprovedTargetStorePort(bindings, maker, engine, loop)
        bridge._drive(bridge.check_ready(), _OPERATION_TIMEOUT_SECONDS)
        authority = ApprovedTargetAuthorityV1(bridge, bindings, scopes)
        return ComponentResources.owned(
            {"approved_target_authority": authority},
            ready=bridge.ready,
            close=bridge.close,
        )
    except BaseException:
        if bridge is not None:
            try:
                bridge.close()
            except BaseException:
                pass
        elif engine is not None:
            try:
                loop.run_until_complete(
                    asyncio.wait_for(engine.dispose(), timeout=_CLOSE_TIMEOUT_SECONDS)
                )
            except BaseException:
                pass
            if not loop.is_closed():
                loop.close()
        elif not loop.is_closed():
            loop.close()
        raise


__all__ = ["create_execution_approved_target_resources"]
