"""Owner-thread adapter for the optional service SDK runtime.

The SDK is deliberately imported only when a session is constructed. Applications
that do not configure service reads therefore do not import or initialize the
optional SDK package. A configured manual-order selector sends only its exact
``orders.submit`` operation through the existing owner thread.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .client import (
    AccountBinding,
    AccountBookBinding,
    ApprovedTargetSubmitBinding,
    AuthorizedServiceReadClient,
    MonitorBinding,
    PortfolioAnalyticsBinding,
    OrderBinding,
    OrderSubmitBinding,
    ServiceReadUnavailableError,
)
from .contracts import (
    AccountBookReadView,
    AccountReadView,
    OrderReadView,
    StrategyHealthView,
    _thaw_json,
)

if TYPE_CHECKING:
    from bt_api_base.service_protocol import WireIdentity
    from bt_api_py.service_runtime import ServiceClientRuntime


@dataclass(frozen=True)
class ServiceReadCloseFailure:
    """One retained cleanup failure, including its original exception object."""

    component: str
    error: BaseException


class ServiceReadSessionError(RuntimeError):
    """Finite session-lifecycle error suitable for the read API boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        failures: tuple[ServiceReadCloseFailure, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failures = failures


class SdkServiceReadSession:
    """Own an SDK runtime and use it only from its constructing thread.

    ``runtime_factory`` must create a fresh runtime whose identity and service
    bindings have already been authorized by the application composition. The
    session checks that configuration against the runtime after registration
    and again before each read. It never derives a WireIdentity from a caller or
    HTTP selector.
    """

    _MANUAL_SUBMIT_ARGUMENTS = frozenset(
        {
            "intent_id",
            "signal_id",
            "instrument",
            "side",
            "position_effect",
            "order_type",
            "quantity",
            "price",
            "time_in_force",
            "reduce_only",
            "metadata_version",
            "deadline_ns",
            "tags",
        }
    )

    def __init__(
        self,
        runtime_factory: Callable[[], Any],
        expected_identity: WireIdentity,
        *,
        account_bindings: Mapping[str, AccountBinding],
        account_book_bindings: Mapping[str, AccountBookBinding] | None = None,
        order_bindings: Mapping[str, OrderBinding] | None = None,
        order_submit_bindings: Mapping[str, OrderSubmitBinding] | None = None,
        approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding] | None = None,
        monitor_bindings: Mapping[str, MonitorBinding] | None = None,
        portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding] | None = None,
    ) -> None:
        self._account_bindings = dict(account_bindings)
        self._account_book_bindings = dict(account_book_bindings or {})
        self._order_bindings = dict(order_bindings or {})
        self._order_submit_bindings = dict(order_submit_bindings or {})
        self._approved_target_bindings = dict(approved_target_bindings or {})
        self._monitor_bindings = dict(monitor_bindings or {})
        self._portfolio_analytics_bindings = dict(portfolio_analytics_bindings or {})
        if not (
            self._account_bindings
            or self._account_book_bindings
            or self._order_bindings
            or self._order_submit_bindings
            or self._approved_target_bindings
            or self._monitor_bindings
            or self._portfolio_analytics_bindings
        ):
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_CONFIGURED",
                "no service-read bindings are configured",
            )

        # SDK imports stay inside construction so an unconfigured deployment
        # does not load the optional package.
        try:
            from bt_api_base.service_protocol import WireIdentity as SdkWireIdentity
            from bt_api_base.service_protocol import WireRole
        except ImportError:
            raise ServiceReadUnavailableError("SDK_NOT_INSTALLED") from None

        if type(expected_identity) is not SdkWireIdentity:
            raise TypeError("expected_identity must be a configured WireIdentity")
        if expected_identity.role is not WireRole.APPLICATION_CLIENT:
            raise ValueError("service reads require an APPLICATION_CLIENT identity")

        self._owner_thread = threading.get_ident()
        self._expected_identity = expected_identity

        self._runtime: ServiceClientRuntime | None = None
        self._read_client: AuthorizedServiceReadClient | None = None
        self._start_attempted = False
        self._started = False
        self._closed = False
        self._close_succeeded = False
        self._close_failures: list[ServiceReadCloseFailure] = []

        runtime = runtime_factory()
        self._runtime = runtime
        try:
            self._check_identity()
            if self._state_name(runtime) != "new":
                raise ServiceReadSessionError(
                    "SERVICE_READ_RUNTIME_NOT_NEW",
                    "runtime_factory must return a new, unstarted runtime",
                )
            self._read_client = AuthorizedServiceReadClient(
                runtime,
                account_bindings=self._account_bindings,
                account_book_bindings=self._account_book_bindings,
                order_bindings=self._order_bindings,
                monitor_bindings=self._monitor_bindings,
            )
        except BaseException as error:
            cleanup_error = self._close_runtime_after_constructor_failure(runtime)
            if cleanup_error is not None:
                try:
                    error.__dict__["service_read_cleanup_error"] = cleanup_error
                except Exception:
                    pass
            raise

    @staticmethod
    def _state_name(runtime: Any) -> str:
        state = runtime.state
        return str(getattr(state, "value", state)).lower()

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise ServiceReadSessionError(
                "SERVICE_READ_WRONG_THREAD",
                "service-read session methods must run on the owner thread",
            )

    def _require_open(self) -> None:
        if self._closed:
            raise ServiceReadUnavailableError("SERVICE_READ_CLOSED")

    def _check_identity(self) -> None:
        assert self._runtime is not None
        from bt_api_base.service_protocol import WireRole

        actual = self._runtime.identity
        if actual != self._expected_identity or actual.role is not WireRole.APPLICATION_CLIENT:
            raise ServiceReadSessionError(
                "SERVICE_READ_IDENTITY_MISMATCH",
                "runtime identity does not match the configured application identity",
            )

    @staticmethod
    def _scope_has_unbounded_account_alias(scope: Any) -> bool:
        return bool(getattr(scope, "account_refs", ()))

    @staticmethod
    def _operations(binding: Any) -> frozenset[str]:
        return frozenset(getattr(binding, "operations", ()))

    @staticmethod
    def _active(binding: Any) -> bool:
        return bool(getattr(binding, "active", False))

    def _expected_binding_specs(self) -> set[tuple[str, str, frozenset[str]]]:
        expected: set[tuple[str, str, frozenset[str]]] = set()
        for binding in self._account_bindings.values():
            expected.add((binding.mount, binding.scope_ref, frozenset({"account.snapshot"})))
        order_query_operations: set[str] = set()
        if self._order_bindings:
            order_query_operations.add("orders.query")
        if self._account_book_bindings:
            order_query_operations.add("execution.account_books.query")
        for binding in self._order_bindings.values():
            expected.add((binding.mount, binding.scope_ref, frozenset(order_query_operations)))
        for binding in self._account_book_bindings.values():
            expected.add((binding.mount, binding.scope_ref, frozenset(order_query_operations)))
        for binding in self._order_submit_bindings.values():
            expected.add((binding.mount, binding.scope_ref, frozenset({"orders.submit"})))
        for binding in self._approved_target_bindings.values():
            expected.add(
                (binding.mount, binding.scope_ref, frozenset({"orders.submit_approved_target"}))
            )
        for binding in self._monitor_bindings.values():
            expected.add((binding.mount, binding.scope_ref, frozenset({"telemetry.snapshot"})))
        analytics_operations = frozenset(
            {
                "analysis.input_upload",
                "analysis.submit",
                "analysis.query",
                "analysis.cancel",
            }
        )
        for binding in self._portfolio_analytics_bindings.values():
            expected.add((binding.mount, binding.scope_ref, analytics_operations))
        return expected

    def _validate_registered_bindings(self) -> None:
        assert self._runtime is not None
        active = [binding for binding in self._runtime.bindings if self._active(binding)]
        expected = self._expected_binding_specs()
        observed = [
            (binding.mount, binding.scope_ref, self._operations(binding)) for binding in active
        ]
        if len(observed) != len(set(observed)) or set(observed) != expected:
            raise ServiceReadSessionError(
                "SERVICE_READ_BINDING_MISMATCH",
                "active runtime bindings do not exactly match configured read bindings",
            )

        for account_ref, configured in self._account_bindings.items():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            scope = binding.scope
            if getattr(
                scope, "account_ref", None
            ) != account_ref or self._scope_has_unbounded_account_alias(scope):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "account binding scope is not exact for its configured account",
                )

        for configured in self._order_bindings.values():
            self._one_registered_binding(configured.mount, configured.scope_ref)

        for configured in self._order_submit_bindings.values():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            if not self._scope_is_manual_order_scope(
                binding.scope, configured.account_ref, configured.manual_book_ref
            ):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "manual-order scope does not match its configured account and book",
                )

        for configured in self._approved_target_bindings.values():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            if not self._scope_is_approved_target_scope(
                binding.scope,
                configured.account_ref,
                configured.strategy_ref,
                configured.wire_scope,
            ):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "approved-target scope does not match its configured owner binding",
                )

        for account_ref, configured in self._account_book_bindings.items():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            if not self._scope_is_account_scope(binding.scope, account_ref):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "account-book scope is not exact for its configured account",
                )

        for configured in self._monitor_bindings.values():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            scope = binding.scope
            if getattr(
                scope, "strategy_ref", None
            ) != configured.strategy_ref or self._scope_has_unbounded_account_alias(scope):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "monitor binding scope does not match its configured strategy",
                )

        for portfolio_ref, configured in self._portfolio_analytics_bindings.items():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            if not self._scope_is_portfolio_analytics_scope(
                binding.scope, portfolio_ref
            ):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "analytics scope does not match its configured portfolio",
                )

    @staticmethod
    def _scope_is_portfolio_analytics_scope(scope: Any, portfolio_ref: str) -> bool:
        return (
            getattr(scope, "portfolio_ref", None) == portfolio_ref
            and getattr(scope, "run_id", None) is None
            and getattr(scope, "account_ref", None) is None
            and not getattr(scope, "account_refs", ())
            and getattr(scope, "strategy_ref", None) is None
            and getattr(scope, "manual_book_ref", None) is None
            and getattr(scope, "group_id", None) is None
            and getattr(scope, "leg_id", None) is None
        )

    def _one_registered_binding(self, mount: str, scope_ref: str) -> Any:
        assert self._runtime is not None
        matches = [
            binding
            for binding in self._runtime.bindings
            if self._active(binding) and binding.mount == mount and binding.scope_ref == scope_ref
        ]
        if len(matches) != 1:
            raise ServiceReadSessionError(
                "SERVICE_READ_BINDING_MISMATCH",
                "expected exactly one active registered binding for the configured scope",
            )
        return matches[0]

    def _validate_runtime(self) -> None:
        assert self._runtime is not None
        self._check_identity()
        if self._state_name(self._runtime) != "registered" or not self._runtime.healthy:
            raise ServiceReadSessionError(
                "SERVICE_READ_RUNTIME_UNHEALTHY",
                "service runtime is not registered and healthy",
            )
        self._validate_registered_bindings()

    def _validate_account_scope(self, account_ref: str, configured: AccountBinding) -> None:
        assert self._runtime is not None
        view = self._runtime.account_binding_view(
            configured.mount,
            account_ref,
            required_operations=frozenset({"account.snapshot"}),
        )
        if (
            view.scope_ref != configured.scope_ref
            or view.account_ref != account_ref
            or view.mount != configured.mount
            or frozenset(view.operations) != frozenset({"account.snapshot"})
            or getattr(view.rpc_scope, "account_ref", None) != account_ref
            or self._scope_has_unbounded_account_alias(view.rpc_scope)
        ):
            raise ServiceReadSessionError(
                "SERVICE_READ_SCOPE_MISMATCH",
                "runtime account scope does not match the trusted account binding",
            )

    @staticmethod
    def _scope_is_account_scope(scope: Any, account_ref: str) -> bool:
        return (
            getattr(scope, "account_ref", None) == account_ref
            and not getattr(scope, "account_refs", ())
            and getattr(scope, "strategy_ref", None) is None
            and getattr(scope, "run_id", None) is None
            and getattr(scope, "manual_book_ref", None) is None
            and getattr(scope, "portfolio_ref", None) is None
            and getattr(scope, "group_id", None) is None
            and getattr(scope, "leg_id", None) is None
        )

    @staticmethod
    def _scope_is_manual_order_scope(
        scope: Any, account_ref: str, manual_book_ref: str
    ) -> bool:
        return (
            getattr(scope, "account_ref", None) == account_ref
            and not getattr(scope, "account_refs", ())
            and getattr(scope, "strategy_ref", None) is None
            and getattr(scope, "manual_book_ref", None) == manual_book_ref
            and getattr(scope, "run_id", None) is None
            and getattr(scope, "portfolio_ref", None) is None
            and getattr(scope, "group_id", None) is None
            and getattr(scope, "leg_id", None) is None
        )

    @staticmethod
    def _scope_is_approved_target_scope(
        scope: Any, account_ref: str, strategy_ref: str, expected_scope: Any
    ) -> bool:
        return (
            type(scope) is type(expected_scope)
            and scope == expected_scope
            and getattr(scope, "account_ref", None) == account_ref
            and not getattr(scope, "account_refs", ())
            and getattr(scope, "strategy_ref", None) == strategy_ref
            and getattr(scope, "manual_book_ref", None) is None
            and getattr(scope, "group_id", None) is None
            and getattr(scope, "leg_id", None) is None
        )

    def start(self) -> None:
        self._assert_owner()
        self._require_open()
        if self._start_attempted:
            raise ServiceReadSessionError(
                "SERVICE_READ_ALREADY_STARTED",
                "service-read runtime start may be attempted only once",
            )
        assert self._runtime is not None
        self._start_attempted = True
        self._check_identity()
        self._runtime.start()
        self._validate_runtime()
        self._started = True

    def maintain(self) -> None:
        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service-read runtime must be started before maintenance",
            )
        assert self._runtime is not None
        self._runtime.maintain()
        self._validate_runtime()

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service-read runtime must be started before reads",
            )
        configured = self._account_bindings.get(account_ref)
        if configured is None:
            raise ServiceReadUnavailableError("ACCOUNT_NOT_CONFIGURED")
        self._validate_runtime()
        self._validate_account_scope(account_ref, configured)
        assert self._read_client is not None
        return self._read_client.read_account(account_ref, currency=currency)

    def read_order(self, scope_ref: str, intent_id: str) -> OrderReadView:
        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service-read runtime must be started before reads",
            )
        configured = self._order_bindings.get(scope_ref)
        if configured is None:
            raise ServiceReadUnavailableError("ORDER_SCOPE_NOT_CONFIGURED")
        self._validate_runtime()
        assert self._read_client is not None
        return self._read_client.read_order(scope_ref, intent_id)

    def submit_manual_order(
        self, scope_ref: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Submit one manual intent on this runtime's existing owner thread."""

        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        configured = self._order_submit_bindings.get(scope_ref)
        if configured is None:
            raise ServiceReadUnavailableError("ORDER_SUBMIT_SCOPE_NOT_CONFIGURED")
        if (
            not isinstance(arguments, Mapping)
            or any(type(key) is not str for key in arguments)
            or set(arguments) != self._MANUAL_SUBMIT_ARGUMENTS
        ):
            raise ServiceReadUnavailableError("INVALID_ORDER_SUBMIT_ARGUMENTS")
        self._validate_runtime()
        assert self._runtime is not None
        return self._runtime.call(
            configured.mount,
            "orders.submit",
            dict(arguments),
            scope_ref=configured.scope_ref,
        )

    def submit_approved_target(
        self, scope_ref: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Submit one approved target through the configured SDK owner."""

        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        configured = self._approved_target_bindings.get(scope_ref)
        if configured is None:
            raise ServiceReadUnavailableError("APPROVED_TARGET_SCOPE_NOT_CONFIGURED")
        if (
            not isinstance(arguments, Mapping)
            or any(type(key) is not str for key in arguments)
            or set(arguments)
            != {"approval_ref", "approval_version", "target_sha256", "intent_id"}
        ):
            raise ServiceReadUnavailableError("INVALID_APPROVED_TARGET_ARGUMENTS")
        self._validate_runtime()
        assert self._runtime is not None
        return self._runtime.call(
            configured.mount,
            "orders.submit_approved_target",
            dict(arguments),
            scope_ref=configured.scope_ref,
        )

    def read_account_book(self, account_ref: str) -> AccountBookReadView:
        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service-read runtime must be started before reads",
            )
        configured = self._account_book_bindings.get(account_ref)
        if configured is None:
            raise ServiceReadUnavailableError("ACCOUNT_BOOK_NOT_CONFIGURED")
        self._validate_runtime()
        assert self._read_client is not None
        return self._read_client.read_account_book(account_ref)

    def upload_portfolio_analytics_input(
        self, scope_ref: str, input_snapshot_id: str, facts: dict[str, Any]
    ) -> Mapping[str, Any]:
        return self._portfolio_analytics_call(
            scope_ref,
            "analysis.input_upload",
            {"input_snapshot_id": input_snapshot_id, "facts": facts},
            {"input_snapshot_id", "facts"},
        )

    def submit_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str, input_snapshot_id: str, request: dict[str, Any]
    ) -> Mapping[str, Any]:
        return self._portfolio_analytics_call(
            scope_ref,
            "analysis.submit",
            {
                "task_ref": task_ref,
                "input_snapshot_id": input_snapshot_id,
                "request": request,
            },
            {"task_ref", "input_snapshot_id", "request"},
        )

    def query_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str
    ) -> Mapping[str, Any]:
        return self._portfolio_analytics_call(
            scope_ref, "analysis.query", {"task_ref": task_ref}, {"task_ref"}
        )

    def cancel_portfolio_analytics_task(
        self, scope_ref: str, task_ref: str
    ) -> Mapping[str, Any]:
        return self._portfolio_analytics_call(
            scope_ref, "analysis.cancel", {"task_ref": task_ref}, {"task_ref"}
        )

    def _portfolio_analytics_call(
        self,
        scope_ref: str,
        operation: str,
        arguments: dict[str, Any],
        expected_arguments: set[str],
    ) -> Mapping[str, Any]:
        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        if set(arguments) != expected_arguments:
            raise ServiceReadUnavailableError("INVALID_ANALYTICS_ARGUMENTS")
        for key in ("task_ref", "input_snapshot_id"):
            if key in arguments and (
                type(arguments[key]) is not str
                or not arguments[key]
                or arguments[key] != arguments[key].strip()
                or len(arguments[key]) > 128
            ):
                raise ServiceReadUnavailableError("INVALID_ANALYTICS_ARGUMENTS")
        for key in ("facts", "request"):
            if key in arguments and type(arguments[key]) is not dict:
                raise ServiceReadUnavailableError("INVALID_ANALYTICS_ARGUMENTS")
        configured = next(
            (
                binding
                for binding in self._portfolio_analytics_bindings.values()
                if binding.scope_ref == scope_ref
            ),
            None,
        )
        if configured is None:
            raise ServiceReadUnavailableError("PORTFOLIO_ANALYTICS_NOT_CONFIGURED")
        self._validate_runtime()
        assert self._runtime is not None
        reply = self._runtime.call(
            configured.mount, operation, arguments, scope_ref=configured.scope_ref
        )
        if not isinstance(reply, Mapping):
            raise ServiceReadUnavailableError("INVALID_ANALYTICS_REPLY")
        # SDK wire replies are recursively frozen as MappingProxyType/tuples.
        # The AFI task parser accepts the corresponding JSON dict/list shape.
        return _thaw_json(reply)

    def read_strategy_health(self, scope_ref: str) -> StrategyHealthView:
        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service-read runtime must be started before reads",
            )
        configured = self._monitor_bindings.get(scope_ref)
        if configured is None:
            raise ServiceReadUnavailableError("MONITOR_SCOPE_NOT_CONFIGURED")
        self._validate_runtime()
        assert self._read_client is not None
        return self._read_client.read_strategy_health(scope_ref)

    def _close_runtime_after_constructor_failure(self, runtime: Any) -> BaseException | None:
        try:
            runtime.close()
        except BaseException as error:
            return error
        if self._runtime_uncertainty(runtime):
            return ServiceReadSessionError(
                "SERVICE_READ_CLEANUP_UNCERTAIN",
                "runtime reported cleanup uncertainty during constructor rollback",
            )
        return None

    @staticmethod
    def _runtime_uncertainty(runtime: Any) -> bool:
        return bool(
            getattr(runtime, "cleanup_failures", 0)
            or getattr(runtime, "unregister_uncertainties", 0)
        )

    @property
    def cleanup_failures(self) -> int:
        return int(getattr(self._runtime, "cleanup_failures", 0))

    @property
    def unregister_uncertainties(self) -> int:
        return int(getattr(self._runtime, "unregister_uncertainties", 0))

    @property
    def close_failures(self) -> tuple[ServiceReadCloseFailure, ...]:
        return tuple(self._close_failures)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def close_succeeded(self) -> bool:
        return self._close_succeeded

    def close(self) -> None:
        self._assert_owner()
        if self._close_succeeded:
            return
        self._closed = True
        failures: list[ServiceReadCloseFailure] = []
        if self._read_client is not None:
            try:
                self._read_client.close()
            except BaseException as error:
                nested = getattr(error, "failures", None)
                if isinstance(nested, tuple) and nested:
                    failures.extend(
                        ServiceReadCloseFailure("account_facade", failure)
                        for failure in nested
                        if isinstance(failure, BaseException)
                    )
                else:
                    failures.append(ServiceReadCloseFailure("read_client", error))
        if self._runtime is not None:
            try:
                self._runtime.close()
            except BaseException as error:
                failures.append(ServiceReadCloseFailure("runtime", error))
            if self._runtime_uncertainty(self._runtime):
                failures.append(
                    ServiceReadCloseFailure(
                        "runtime_uncertainty",
                        ServiceReadSessionError(
                            "SERVICE_READ_CLEANUP_UNCERTAIN",
                            "runtime close reported cleanup or unregister uncertainty",
                        ),
                    )
                )
        self._close_failures.extend(failures)
        if failures:
            self._close_succeeded = False
            error = ServiceReadSessionError(
                "SERVICE_READ_CLOSE_FAILED",
                "one or more service-read resources did not close cleanly",
                failures=tuple(failures),
            )
            raise error from failures[0].error
        self._close_succeeded = True
