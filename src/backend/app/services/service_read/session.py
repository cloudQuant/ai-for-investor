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
    PaperLegacyImportBinding,
    PAPER_LEGACY_IMPORT_OPERATIONS,
    PaperSubmitBinding,
    RiskAccountPolicyBinding,
    RiskPolicyBudgetBinding,
    ServiceReadUnavailableError,
)
from .contracts import (
    AccountBookReadView,
    AccountReadView,
    OrderReadView,
    StrategyHealthView,
    _thaw_json,
)
from .gateway_health import GatewayHealthView

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

    _PAPER_SUBMIT_ARGUMENTS = frozenset(_MANUAL_SUBMIT_ARGUMENTS)

    def __init__(
        self,
        runtime_factory: Callable[[], Any],
        expected_identity: WireIdentity,
        *,
        account_bindings: Mapping[str, AccountBinding],
        account_book_bindings: Mapping[str, AccountBookBinding] | None = None,
        order_bindings: Mapping[str, OrderBinding] | None = None,
        order_submit_bindings: Mapping[str, OrderSubmitBinding] | None = None,
        paper_submit_bindings: Mapping[str, PaperSubmitBinding] | None = None,
        paper_legacy_import_bindings: Mapping[str, PaperLegacyImportBinding] | None = None,
        approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding] | None = None,
        monitor_bindings: Mapping[str, MonitorBinding] | None = None,
        portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding] | None = None,
        risk_policy_budget_bindings: Mapping[str, RiskPolicyBudgetBinding] | None = None,
        risk_account_policy_bindings: Mapping[str, RiskAccountPolicyBinding] | None = None,
    ) -> None:
        self._account_bindings = dict(account_bindings)
        self._account_book_bindings = dict(account_book_bindings or {})
        self._order_bindings = dict(order_bindings or {})
        self._order_submit_bindings = dict(order_submit_bindings or {})
        self._paper_submit_bindings = dict(paper_submit_bindings or {})
        self._paper_submit_bindings_by_scope = {
            binding.scope_ref: binding for binding in self._paper_submit_bindings.values()
        }
        if len(self._paper_submit_bindings_by_scope) != len(self._paper_submit_bindings):
            raise ServiceReadSessionError(
                "SERVICE_READ_BINDING_MISMATCH",
                "paper submit scopes must be unique within a session",
            )
        self._paper_legacy_import_bindings = dict(paper_legacy_import_bindings or {})
        self._approved_target_bindings = dict(approved_target_bindings or {})
        self._monitor_bindings = dict(monitor_bindings or {})
        self._portfolio_analytics_bindings = dict(portfolio_analytics_bindings or {})
        self._risk_policy_budget_bindings = dict(risk_policy_budget_bindings or {})
        self._risk_account_policy_bindings = dict(risk_account_policy_bindings or {})
        if not (
            self._account_bindings
            or self._account_book_bindings
            or self._order_bindings
            or self._order_submit_bindings
            or self._paper_submit_bindings
            or self._paper_legacy_import_bindings
            or self._approved_target_bindings
            or self._monitor_bindings
            or self._portfolio_analytics_bindings
            or self._risk_policy_budget_bindings
            or self._risk_account_policy_bindings
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
            expected.add(
                (
                    binding.mount,
                    binding.scope_ref,
                    frozenset({"account.snapshot", "account.head"}),
                )
            )
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
        for binding in self._paper_submit_bindings.values():
            expected.add((binding.mount, binding.scope_ref, frozenset({"orders.submit"})))
        for binding in self._paper_legacy_import_bindings.values():
            expected.add((binding.mount, binding.scope_ref, PAPER_LEGACY_IMPORT_OPERATIONS))
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
        for binding in self._risk_policy_budget_bindings.values():
            expected.add(
                (binding.mount, binding.management_scope_ref, binding.operations)
            )
            for scope_ref in binding.member_scope_refs.values():
                expected.add((binding.mount, scope_ref, binding.operations))
        for binding in self._risk_account_policy_bindings.values():
            expected.add((binding.mount, binding.scope_ref, binding.operations))
        return expected

    @staticmethod
    def _scope_is_manual_policy_scope(scope: Any, account_ref: str) -> bool:
        return (
            getattr(scope, "account_ref", None) == account_ref
            and not getattr(scope, "account_refs", ())
            and bool(getattr(scope, "execution_domain_ref", None))
            and bool(getattr(scope, "manual_book_ref", None))
            and getattr(scope, "strategy_ref", None) is None
            and getattr(scope, "run_id", None) is None
            and getattr(scope, "portfolio_ref", None) is None
            and getattr(scope, "group_id", None) is None
            and getattr(scope, "leg_id", None) is None
        )

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

        for configured in self._paper_submit_bindings.values():
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            scope = binding.scope
            try:
                configured.paper_owner_domain.validate_binding(
                    configured.wire_scope, configured.execution_scope
                )
            except Exception:
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "paper owner domain no longer validates against its trusted scope",
                ) from None
            if (
                type(scope) is not type(configured.wire_scope)
                or scope != configured.wire_scope
                or not self._scope_is_paper_order_scope(
                    scope,
                    configured.account_ref,
                    configured.execution_domain_ref,
                    configured.strategy_ref,
                )
            ):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "paper submit scope does not match its configured owner domain",
                )

        for configured in self._paper_legacy_import_bindings.values():
            paper = configured.paper_binding
            binding = self._one_registered_binding(configured.mount, configured.scope_ref)
            scope = binding.scope
            try:
                paper.paper_owner_domain.validate_binding(paper.wire_scope, paper.execution_scope)
            except Exception:
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "legacy import target no longer validates against its trusted paper owner",
                ) from None
            if (
                type(scope) is not type(paper.wire_scope)
                or scope != paper.wire_scope
                or configured.scope_ref != paper.scope_ref
                or configured.legacy_account_id != paper.legacy_account_id
                or not self._scope_is_paper_order_scope(
                    scope,
                    paper.account_ref,
                    paper.execution_domain_ref,
                    paper.strategy_ref,
                )
            ):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "legacy import scope does not match its trusted paper owner",
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

        for portfolio_ref, configured in self._risk_policy_budget_bindings.items():
            if configured.portfolio_ref != portfolio_ref:
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "budget selector does not match its configured portfolio",
                )
            management = self._one_registered_binding(
                configured.mount, configured.management_scope_ref
            ).scope
            if not self._scope_is_budget_management_scope(
                management, portfolio_ref, frozenset(configured.member_scope_refs)
            ):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "budget management scope does not match its configured members",
                )
            for account_ref, scope_ref in configured.member_scope_refs.items():
                member = self._one_registered_binding(configured.mount, scope_ref).scope
                if not self._scope_is_budget_member_scope(
                    member, portfolio_ref, account_ref, management.execution_domain_ref
                ):
                    raise ServiceReadSessionError(
                        "SERVICE_READ_SCOPE_MISMATCH",
                        "budget member scope does not match its configured account",
                    )

        for account_ref, configured in self._risk_account_policy_bindings.items():
            if configured.account_ref != account_ref:
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "account policy selector does not match its configured account",
                )
            scope = self._one_registered_binding(
                configured.mount, configured.scope_ref
            ).scope
            if not self._scope_is_manual_policy_scope(scope, account_ref):
                raise ServiceReadSessionError(
                    "SERVICE_READ_SCOPE_MISMATCH",
                    "account policy scope must be one exact manual account target",
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

    @staticmethod
    def _scope_is_budget_management_scope(
        scope: Any, portfolio_ref: str, account_refs: frozenset[str]
    ) -> bool:
        return (
            getattr(scope, "portfolio_ref", None) == portfolio_ref
            and getattr(scope, "account_ref", None) is None
            and frozenset(getattr(scope, "account_refs", ())) == account_refs
            and bool(getattr(scope, "execution_domain_ref", None))
            and getattr(scope, "run_id", None) is None
            and getattr(scope, "strategy_ref", None) is None
            and getattr(scope, "manual_book_ref", None) is None
            and getattr(scope, "group_id", None) is None
            and getattr(scope, "leg_id", None) is None
        )

    @staticmethod
    def _scope_is_budget_member_scope(
        scope: Any, portfolio_ref: str, account_ref: str, execution_domain_ref: str
    ) -> bool:
        return (
            getattr(scope, "portfolio_ref", None) == portfolio_ref
            and getattr(scope, "account_ref", None) == account_ref
            and not getattr(scope, "account_refs", ())
            and getattr(scope, "execution_domain_ref", None) == execution_domain_ref
            and getattr(scope, "run_id", None) is None
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
            required_operations=frozenset({"account.snapshot", "account.head"}),
        )
        if (
            view.scope_ref != configured.scope_ref
            or view.account_ref != account_ref
            or view.mount != configured.mount
            or frozenset(view.operations)
            != frozenset({"account.snapshot", "account.head"})
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
    def _scope_is_paper_order_scope(
        scope: Any, account_ref: str, execution_domain_ref: str, strategy_ref: str
    ) -> bool:
        return (
            getattr(scope, "execution_domain_ref", None) == execution_domain_ref
            and getattr(scope, "account_ref", None) == account_ref
            and not getattr(scope, "account_refs", ())
            and getattr(scope, "strategy_ref", None) == strategy_ref
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

    def read_gateway_health(self, account_ref: str) -> GatewayHealthView:
        """Read Gateway owner status and account facts as separate observations."""

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
        assert self._runtime is not None
        assert self._read_client is not None
        head_reply = self._runtime.call(
            configured.mount,
            "account.head",
            {},
            scope_ref=configured.scope_ref,
        )
        account_observation = self._read_client.read_account(account_ref)
        return GatewayHealthView.from_replies(
            account_ref,
            head_reply,
            account_observation,
        )

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

    def submit_paper_order(
        self, scope_ref: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Submit one exact paper-owner intent through the existing runtime."""

        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        configured = self._paper_submit_bindings_by_scope.get(scope_ref)
        if configured is None:
            raise ServiceReadUnavailableError("PAPER_SUBMIT_SCOPE_NOT_CONFIGURED")
        if (
            not isinstance(arguments, Mapping)
            or any(type(key) is not str for key in arguments)
            or set(arguments) != self._PAPER_SUBMIT_ARGUMENTS
        ):
            raise ServiceReadUnavailableError("INVALID_PAPER_SUBMIT_ARGUMENTS")
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

    def call_risk_policy_budget(
        self,
        portfolio_ref: str,
        operation: str,
        arguments: dict[str, Any],
        *,
        member_account_ref: str | None = None,
    ) -> dict[str, Any]:
        """Call one fixed Risk catalog operation on its configured owner thread."""

        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        binding = self._risk_policy_budget_bindings.get(portfolio_ref)
        if binding is None:
            raise ServiceReadUnavailableError("RISK_POLICY_BUDGET_NOT_CONFIGURED")
        if operation not in binding.operations:
            raise ServiceReadUnavailableError("RISK_POLICY_BUDGET_OPERATION_NOT_AUTHORIZED")
        expected_arguments: dict[str, frozenset[str]] = {
            "policy.draft": frozenset({"policy_ref", "content"}),
            "policy.budget.propose": frozenset(
                {
                    "pool_ref",
                    "generation_ref",
                    "portfolio_ref",
                    "membership_version",
                    "membership_sha256",
                    "allocation_set_sha256",
                    "currency",
                    "metric",
                    "total_amount",
                    "unallocated_amount",
                    "allocations",
                }
            ),
            "policy.budget.approve": frozenset({"generation_ref"}),
            "policy.budget.publish_member": frozenset(
                {"generation_ref", "account_ref"}
            ),
            "policy.budget.confirm_member": frozenset(
                {"generation_ref", "account_ref"}
            ),
            "policy.budget.owner_confirm_member": frozenset(
                {"generation_ref", "account_ref"}
            ),
            "policy.budget.reject_member": frozenset(
                {"generation_ref", "account_ref"}
            ),
            "policy.budget.mark_unknown": frozenset({"generation_ref"}),
            "policy.budget.retract": frozenset({"generation_ref"}),
            "policy.budget.read": frozenset({"generation_ref"}),
        }
        required = expected_arguments.get(operation)
        if required is None or set(arguments) != required:
            raise ServiceReadUnavailableError("INVALID_RISK_POLICY_BUDGET_ARGUMENTS")
        member_operations = {
            "policy.draft",
            "policy.budget.confirm_member",
            "policy.budget.owner_confirm_member",
            "policy.budget.reject_member",
        }
        if operation in member_operations:
            if (
                type(member_account_ref) is not str
                or member_account_ref not in binding.member_scope_refs
                or (
                    operation
                    in {
                        "policy.budget.confirm_member",
                        "policy.budget.owner_confirm_member",
                        "policy.budget.reject_member",
                    }
                    and arguments.get("account_ref") != member_account_ref
                )
            ):
                raise ServiceReadUnavailableError("RISK_POLICY_BUDGET_MEMBER_NOT_CONFIGURED")
            scope_ref = binding.member_scope_refs[member_account_ref]
        else:
            if member_account_ref is not None:
                raise ServiceReadUnavailableError("INVALID_RISK_POLICY_BUDGET_SCOPE")
            if operation in {
                "policy.budget.publish_member",
            } and arguments.get("account_ref") not in binding.member_scope_refs:
                raise ServiceReadUnavailableError("RISK_POLICY_BUDGET_MEMBER_NOT_CONFIGURED")
            scope_ref = binding.management_scope_ref

        self._validate_runtime()
        assert self._runtime is not None
        reply = _thaw_json(
            self._runtime.call(
                binding.mount,
                operation,
                dict(arguments),
                scope_ref=scope_ref,
            )
        )
        if (
            type(reply) is not dict
            or set(reply) != {"ok", "code", "result"}
            or type(reply["ok"]) is not bool
            or type(reply["code"]) is not str
            or type(reply["result"]) is not dict
        ):
            raise ServiceReadUnavailableError("INVALID_RISK_POLICY_BUDGET_REPLY")
        return reply

    def call_risk_account_policy(
        self,
        account_ref: str,
        operation: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Call one explicitly granted ordinary account-policy operation."""

        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        binding = self._risk_account_policy_bindings.get(account_ref)
        if binding is None:
            raise ServiceReadUnavailableError("RISK_ACCOUNT_POLICY_NOT_CONFIGURED")
        if operation not in binding.operations:
            raise ServiceReadUnavailableError(
                "RISK_ACCOUNT_POLICY_OPERATION_NOT_AUTHORIZED"
            )
        expected_arguments: dict[str, frozenset[str]] = {
            "policy.draft": frozenset({"policy_ref", "content"}),
            "policy.approve": frozenset({"policy_ref"}),
            "policy.publish": frozenset({"policy_ref"}),
            "policy.inspect": frozenset({"policy_ref"}),
            "policy.receipt": frozenset({"policy_ref"}),
            "policy.confirmation.read": frozenset({"policy_ref"}),
        }
        required = expected_arguments.get(operation)
        if required is None or set(arguments) != required:
            raise ServiceReadUnavailableError(
                "INVALID_RISK_ACCOUNT_POLICY_ARGUMENTS"
            )
        self._validate_runtime()
        assert self._runtime is not None
        reply = _thaw_json(
            self._runtime.call(
                binding.mount,
                operation,
                dict(arguments),
                scope_ref=binding.scope_ref,
            )
        )
        if (
            type(reply) is not dict
            or set(reply) != {"ok", "code", "result"}
            or type(reply["ok"]) is not bool
            or type(reply["code"]) is not str
            or type(reply["result"]) is not dict
        ):
            raise ServiceReadUnavailableError("INVALID_RISK_ACCOUNT_POLICY_REPLY")
        return reply

    def call_paper_legacy_import(
        self,
        legacy_account_id: str,
        operation: str,
        arguments: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Call one explicit import operation through the trusted Host binding."""

        self._assert_owner()
        self._require_open()
        if not self._started:
            raise ServiceReadSessionError(
                "SERVICE_READ_NOT_STARTED",
                "service runtime must be started before operations",
            )
        configured = self._paper_legacy_import_bindings.get(legacy_account_id)
        if configured is None:
            raise ServiceReadUnavailableError("PAPER_LEGACY_IMPORT_NOT_CONFIGURED")
        if type(operation) is not str or operation not in PAPER_LEGACY_IMPORT_OPERATIONS:
            raise ServiceReadUnavailableError("INVALID_PAPER_LEGACY_IMPORT_OPERATION")
        if not isinstance(arguments, Mapping) or any(type(key) is not str for key in arguments):
            raise ServiceReadUnavailableError("INVALID_PAPER_LEGACY_IMPORT_ARGUMENTS")
        expected_arguments = {
            "paper.import.status": frozenset(),
            "paper.import.inspect_source": frozenset({"source_account_id"}),
            "paper.import.prepare": frozenset({"imported"}),
            "paper.import.activate": frozenset(),
            "paper.import.abort": frozenset({"source_sha256"}),
        }
        if set(arguments) != expected_arguments[operation]:
            raise ServiceReadUnavailableError("INVALID_PAPER_LEGACY_IMPORT_ARGUMENTS")

        imported = None
        if operation == "paper.import.inspect_source":
            if arguments.get("source_account_id") != configured.legacy_account_id:
                raise ServiceReadUnavailableError("PAPER_LEGACY_IMPORT_BINDING_MISMATCH")
        elif operation == "paper.import.prepare":
            try:
                from bt_api_execution.paper_legacy_import import PaperLegacyImportV1

                imported = PaperLegacyImportV1.from_payload(arguments["imported"])
                imported.validate_new_import()
                imported.validate_domain(
                    configured.paper_binding.execution_scope,
                    configured.paper_binding.paper_owner_domain,
                )
            except Exception:
                raise ServiceReadUnavailableError("INVALID_PAPER_LEGACY_IMPORT_SNAPSHOT") from None
            if (
                imported.source_account_id != configured.legacy_account_id
                or imported.source_owner_id != configured.owner_subject
                or imported.symbol_bindings != configured.symbol_bindings
            ):
                raise ServiceReadUnavailableError("PAPER_LEGACY_IMPORT_BINDING_MISMATCH")
        elif operation == "paper.import.abort":
            source_sha256 = arguments.get("source_sha256")
            if (
                type(source_sha256) is not str
                or len(source_sha256) != 64
                or any(character not in "0123456789abcdef" for character in source_sha256)
            ):
                raise ServiceReadUnavailableError("INVALID_PAPER_LEGACY_IMPORT_ARGUMENTS")

        self._validate_runtime()
        assert self._runtime is not None
        try:
            from bt_api_py.service_paper_legacy_import_client import PaperLegacyImportClient

            client = PaperLegacyImportClient(
                self._runtime,
                account_ref=configured.paper_binding.account_ref,
                scope_ref=configured.scope_ref,
            )
        except ImportError:
            raise ServiceReadUnavailableError("PAPER_LEGACY_IMPORT_CLIENT_UNAVAILABLE") from None
        if operation == "paper.import.status":
            reply = client.status()
        elif operation == "paper.import.inspect_source":
            reply = client.inspect_source(configured.legacy_account_id)
        elif operation == "paper.import.prepare":
            assert imported is not None
            reply = client.prepare(imported)
        elif operation == "paper.import.activate":
            reply = client.activate()
        else:
            reply = client.abort(arguments["source_sha256"])
        return {
            "ok": reply.ok,
            "code": reply.code,
            "result": _thaw_json(reply.result),
        }

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
