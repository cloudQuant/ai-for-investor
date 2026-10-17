"""Borrowed read adapters from the application to the shared service packages.

The application is an ordinary SDK client: it registers as an application
client, is granted exactly the scopes the deployment authorized, and reads
authorized views.  It owns no provider credential and never opens a provider
session, so an unavailable service degrades to an explicit marker instead of a
hidden direct connection.

``bt_api_py`` is imported lazily inside the methods.  The application must stay
importable and usable when the optional service packages are absent, exactly
like its other optional integrations.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from app.services.service_read.contracts import (
    AccountBookReadView,
    AccountReadView,
    OrderReadView,
    ReadQuality,
    ServiceReadContractError,
    StrategyHealthView,
)

__all__ = [
    "AccountBookBinding",
    "AccountBinding",
    "AuthorizedServiceReadClient",
    "MonitorBinding",
    "PortfolioAnalyticsBinding",
    "OrderBinding",
    "OrderSubmitBinding",
    "PaperSubmitBinding",
    "PaperLegacyImportBinding",
    "ApprovedTargetSubmitBinding",
    "RiskPolicyBudgetBinding",
    "ServiceReadClientCloseError",
    "ServiceReadUnavailableError",
    "PAPER_CONTROL_MODES",
]

PAPER_CONTROL_MODES = frozenset(
    {"execution_only", "execution_risk", "execution_risk_monitor"}
)


RISK_POLICY_BUDGET_MAKER_OPERATIONS = frozenset(
    {
        "policy.draft",
        "policy.budget.propose",
        "policy.budget.publish_member",
        "policy.budget.owner_confirm_member",
        "policy.budget.reject_member",
        "policy.budget.mark_unknown",
        "policy.budget.retract",
        "policy.budget.read",
    }
)
RISK_POLICY_BUDGET_CHECKER_OPERATIONS = frozenset(
    {"policy.budget.approve", "policy.budget.read"}
)
RISK_POLICY_BUDGET_OPERATIONS = frozenset(
    RISK_POLICY_BUDGET_MAKER_OPERATIONS | RISK_POLICY_BUDGET_CHECKER_OPERATIONS
)

PAPER_LEGACY_IMPORT_OPERATIONS = frozenset(
    {
        "paper.import.status",
        "paper.import.inspect_source",
        "paper.import.prepare",
        "paper.import.activate",
        "paper.import.abort",
    }
)

class ServiceReadUnavailableError(RuntimeError):
    """The authorized read path refused or could not answer this request.

    ``code`` is a finite diagnostic.  Callers must surface it instead of
    projecting a placeholder balance or health value.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ServiceReadClientCloseError(RuntimeError):
    """One or more cached account facades could not be closed.

    Failed facade objects remain in the client's cache for inspection and a
    later close retry. The exception retains every original failure object.
    """

    code = "SERVICE_READ_CLOSE_FAILED"

    def __init__(self, failures: tuple[BaseException, ...]) -> None:
        self.failures = failures
        super().__init__(self.code)


#: Registry outcomes that mean the request was refused, not merely degraded.
_REFUSAL_CODES = frozenset(
    {
        "CAPABILITY_UNAVAILABLE",
        "DENIED",
        "DUPLICATE_ACTIVE_RUN",
        "NOT_REGISTERED",
        "POLICY_REQUIREMENT_UNMET",
        "SCOPE_DENIED",
        "STALE_EPOCH",
    }
)

_SNAPSHOT_FIELDS = frozenset({"state", "streams"})
_STREAM_FIELDS = frozenset(
    {
        "producer",
        "scope",
        "stream_id",
        "sequence",
        "status",
        "received_age_seconds",
        "heartbeat_age_seconds",
        "heartbeat",
        "metrics_age_seconds",
        "metrics",
    }
)
_METRIC_NAME_LIMIT = 64
_MAX_ORDER_INSTRUMENT_METADATA_VERSIONS = 256
_ORDER_INSTRUMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,191}$")


@dataclass(frozen=True)
class AccountBinding:
    """One authorized account read the deployment has granted to the app."""

    mount: str
    scope_ref: str
    currency: str
    account_key: Any
    coverage: tuple[Any, ...]
    require_open_orders: bool = False

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
            (self.currency, "INVALID_CURRENCY"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if self.account_key is None:
            raise ServiceReadContractError("INVALID_ACCOUNT_KEY")
        if type(self.coverage) is not tuple or not self.coverage:
            raise ServiceReadContractError("INVALID_COVERAGE")
        if type(self.require_open_orders) is not bool:
            raise ServiceReadContractError("INVALID_REQUIRE_OPEN_ORDERS")


@dataclass(frozen=True)
class AccountBookBinding:
    """One trusted account-level execution-book scope and full AccountKey."""

    mount: str
    scope_ref: str
    account_key: Any

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if type(getattr(self.account_key, "account_key_id", None)) is not str:
            raise ServiceReadContractError("INVALID_ACCOUNT_KEY")


@dataclass(frozen=True)
class OrderBinding:
    """One authorized order-read scope the deployment has granted to the app."""

    mount: str
    scope_ref: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)


@dataclass(frozen=True)
class OrderSubmitBinding:
    """One deployment-owned manual-order scope on the normal E owner port."""

    mount: str
    scope_ref: str
    account_ref: str
    manual_book_ref: str
    instrument_metadata_versions: Mapping[str, str] = field(
        default_factory=dict, repr=False, hash=False
    )

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
            (self.account_ref, "INVALID_ACCOUNT_REF"),
            (self.manual_book_ref, "INVALID_MANUAL_BOOK_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        raw_versions = self.instrument_metadata_versions
        if (
            not isinstance(raw_versions, Mapping)
            or len(raw_versions) > _MAX_ORDER_INSTRUMENT_METADATA_VERSIONS
        ):
            raise ServiceReadContractError("INVALID_INSTRUMENT_METADATA_VERSIONS")
        copied_versions: dict[str, str] = {}
        for instrument, version in raw_versions.items():
            if (
                type(instrument) is not str
                or not _ORDER_INSTRUMENT_RE.fullmatch(instrument)
                or type(version) is not str
                or not version
                or version != version.strip()
                or len(version) > 256
                or not version.isprintable()
                or version == "*"
            ):
                raise ServiceReadContractError("INVALID_INSTRUMENT_METADATA_VERSIONS")
            copied_versions[instrument] = version
        object.__setattr__(
            self,
            "instrument_metadata_versions",
            MappingProxyType(copied_versions),
        )


@dataclass(frozen=True, slots=True)
class PaperSubmitBinding:
    """One trusted paper composition and its exact query/domain bindings."""

    control_mode: str
    mount: str
    scope_ref: str
    query_scope_ref: str
    legacy_account_id: str
    account_ref: str
    execution_domain_ref: str
    strategy_ref: str
    paper_owner_domain: Any = field(repr=False, compare=False)
    wire_scope: Any = field(repr=False, compare=False)
    execution_scope: Any = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.control_mode) is not str
            or self.control_mode not in PAPER_CONTROL_MODES
        ):
            raise ServiceReadContractError("INVALID_PAPER_CONTROL_MODE")
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
            (self.query_scope_ref, "INVALID_SCOPE_REF"),
            (self.legacy_account_id, "INVALID_LEGACY_ACCOUNT_ID"),
            (self.account_ref, "INVALID_ACCOUNT_REF"),
            (self.execution_domain_ref, "INVALID_EXECUTION_DOMAIN_REF"),
            (self.strategy_ref, "INVALID_STRATEGY_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if self.mount != "application.orders":
            raise ServiceReadContractError("INVALID_PAPER_SUBMIT_MOUNT")
        domain = self.paper_owner_domain
        if (
            not callable(getattr(domain, "validate_binding", None))
            or type(getattr(domain, "fingerprint", None)) is not str
            or getattr(domain, "simulation_account_ref", None) != self.account_ref
            or getattr(domain, "execution_domain_ref", None) != self.execution_domain_ref
            or getattr(domain, "strategy_ref", None) != self.strategy_ref
        ):
            raise ServiceReadContractError("INVALID_PAPER_OWNER_DOMAIN")
        try:
            domain.validate_binding(self.wire_scope, self.execution_scope)
        except Exception:
            raise ServiceReadContractError("INVALID_PAPER_SCOPE_BINDING") from None

    @property
    def paper_domain_sha256(self) -> str:
        """Return the digest of the parsed trusted SDK paper domain."""

        return self.paper_owner_domain.fingerprint

    @property
    def initial_cash(self) -> Decimal:
        return self.paper_owner_domain.initial_cash

    @property
    def experiment_ref(self) -> str:
        return self.paper_owner_domain.experiment_ref

    @property
    def model_ref(self) -> str:
        return self.paper_owner_domain.model_ref

    @property
    def model_version(self) -> str:
        return self.paper_owner_domain.model_version

    @property
    def quote_source_ref(self) -> str:
        return self.paper_owner_domain.quote_source_ref

    @property
    def cash_currency(self) -> str:
        return self.paper_owner_domain.cash_currency

    @property
    def initial_fees(self) -> Decimal:
        return self.paper_owner_domain.initial_fees

    @property
    def fee_rate(self) -> Decimal:
        return self.paper_owner_domain.fee_rate

    @property
    def fee_quantum(self) -> Decimal:
        return self.paper_owner_domain.fee_quantum

    @property
    def max_quote_age_ns(self) -> int:
        return self.paper_owner_domain.max_quote_age_ns

    @property
    def instrument_metadata_versions(self) -> Mapping[str, str]:
        return {
            instrument.instrument: instrument.metadata_version
            for instrument in self.paper_owner_domain.instruments
        }

    @property
    def opening_positions(self) -> tuple[Any, ...]:
        return tuple(item.to_payload() for item in self.paper_owner_domain.opening_positions)


@dataclass(frozen=True, slots=True)
class PaperLegacyImportBinding:
    """A separately granted legacy-import route for one existing Paper owner."""

    mount: str
    owner_subject: str
    legacy_account_id: str
    scope_ref: str
    paper_binding: PaperSubmitBinding = field(repr=False, compare=False)
    symbol_bindings: tuple[Any, ...] = field(repr=False)

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.owner_subject, "INVALID_OWNER_SUBJECT"),
            (self.legacy_account_id, "INVALID_LEGACY_ACCOUNT_ID"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if self.mount != "application.paper_legacy_import":
            raise ServiceReadContractError("INVALID_PAPER_LEGACY_IMPORT_MOUNT")
        binding = self.paper_binding
        if (
            type(binding) is not PaperSubmitBinding
            or binding.legacy_account_id != self.legacy_account_id
            or binding.scope_ref != self.scope_ref
        ):
            raise ServiceReadContractError("PAPER_LEGACY_IMPORT_BINDING_MISMATCH")
        if type(self.symbol_bindings) is not tuple:
            raise ServiceReadContractError("INVALID_PAPER_LEGACY_SYMBOL_BINDINGS")
        try:
            from bt_api_execution.paper_legacy_import import LegacyPaperSymbolBindingV1
        except ImportError:
            raise ServiceReadContractError("PAPER_EXECUTION_NOT_INSTALLED") from None
        if any(type(item) is not LegacyPaperSymbolBindingV1 for item in self.symbol_bindings):
            raise ServiceReadContractError("INVALID_PAPER_LEGACY_SYMBOL_BINDINGS")
        legacy_symbols = [item.legacy_symbol for item in self.symbol_bindings]
        instruments = {item.instrument for item in binding.paper_owner_domain.instruments}
        if (
            len(legacy_symbols) != len(set(legacy_symbols))
            or any(item.target_instrument not in instruments for item in self.symbol_bindings)
        ):
            raise ServiceReadContractError("INVALID_PAPER_LEGACY_SYMBOL_BINDINGS")


@dataclass(frozen=True)
class ApprovedTargetSubmitBinding:
    """One trusted strategy/account scope for approved-target submission."""

    mount: str
    scope_ref: str
    account_ref: str
    strategy_ref: str
    expected_scope_ref: str
    wire_scope: Any = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
            (self.account_ref, "INVALID_ACCOUNT_REF"),
            (self.strategy_ref, "INVALID_STRATEGY_REF"),
            (self.expected_scope_ref, "INVALID_SCOPE_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if self.mount != "application.orders":
            raise ServiceReadContractError("INVALID_MOUNT")
        scope = self.wire_scope
        if (
            getattr(scope, "account_ref", None) != self.account_ref
            or getattr(scope, "account_refs", ())
            or getattr(scope, "strategy_ref", None) != self.strategy_ref
            or getattr(scope, "manual_book_ref", None) is not None
            or getattr(scope, "group_id", None) is not None
            or getattr(scope, "leg_id", None) is not None
        ):
            raise ServiceReadContractError("INVALID_APPROVED_TARGET_SCOPE")


@dataclass(frozen=True)
class PortfolioAnalyticsBinding:
    """One deployment-owned offline analytics scope for an exact portfolio."""

    mount: str
    scope_ref: str
    portfolio_ref: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
            (self.portfolio_ref, "INVALID_PORTFOLIO_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if self.mount != "application.risk_analysis":
            raise ServiceReadContractError("INVALID_MOUNT")


@dataclass(frozen=True)
class RiskPolicyBudgetBinding:
    """One trusted actor's pool view and exact catalog/member scopes.

    Actor roles and principal references come from service-read deployment
    configuration, never from an HTTP request. Legacy single-maker profiles
    omit delegation fields and cannot approve a generation.
    """

    mount: str
    pool_ref: str
    portfolio_ref: str
    management_scope_ref: str
    member_scope_refs: Mapping[str, str]
    owner_subject: str | None = None
    actor_role: str = "maker"
    maker_principal_ref: str | None = None
    checker_principal_ref: str | None = None

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.pool_ref, "INVALID_POOL_REF"),
            (self.portfolio_ref, "INVALID_PORTFOLIO_REF"),
            (self.management_scope_ref, "INVALID_SCOPE_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)
        if self.mount != "application.risk_policy":
            raise ServiceReadContractError("INVALID_MOUNT")
        if self.actor_role not in {"maker", "checker"}:
            raise ServiceReadContractError("INVALID_RISK_POLICY_BUDGET_ACTOR_ROLE")
        explicit_actor_binding = any(
            value is not None
            for value in (
                self.owner_subject,
                self.maker_principal_ref,
                self.checker_principal_ref,
            )
        )
        if explicit_actor_binding:
            for value, code in (
                (self.owner_subject, "INVALID_OWNER_SUBJECT"),
                (self.maker_principal_ref, "INVALID_MAKER_PRINCIPAL"),
            ):
                if type(value) is not str or not value or value != value.strip():
                    raise ServiceReadContractError(code)
            if self.checker_principal_ref is not None and (
                type(self.checker_principal_ref) is not str
                or not self.checker_principal_ref
                or self.checker_principal_ref != self.checker_principal_ref.strip()
            ):
                raise ServiceReadContractError("INVALID_CHECKER_PRINCIPAL")
            if self.actor_role == "checker" and self.checker_principal_ref is None:
                raise ServiceReadContractError("INVALID_CHECKER_PRINCIPAL")
            if (
                self.checker_principal_ref is not None
                and self.maker_principal_ref == self.checker_principal_ref
            ):
                raise ServiceReadContractError("MAKER_CHECKER_PRINCIPAL_MUST_DIFFER")
        if not isinstance(self.member_scope_refs, Mapping) or not self.member_scope_refs:
            raise ServiceReadContractError("INVALID_MEMBER_SCOPES")
        members: dict[str, str] = {}
        for account_ref, scope_ref in self.member_scope_refs.items():
            if (
                type(account_ref) is not str
                or not account_ref
                or account_ref != account_ref.strip()
                or type(scope_ref) is not str
                or not scope_ref
                or scope_ref != scope_ref.strip()
            ):
                raise ServiceReadContractError("INVALID_MEMBER_SCOPES")
            members[account_ref] = scope_ref
        scope_refs = [self.management_scope_ref, *members.values()]
        if len(set(scope_refs)) != len(scope_refs):
            raise ServiceReadContractError("DUPLICATE_SCOPE_REF")
        object.__setattr__(self, "member_scope_refs", MappingProxyType(dict(sorted(members.items()))))

    @property
    def operations(self) -> frozenset[str]:
        return (
            RISK_POLICY_BUDGET_CHECKER_OPERATIONS
            if self.actor_role == "checker"
            else RISK_POLICY_BUDGET_MAKER_OPERATIONS
        )

    @property
    def expected_principal_ref(self) -> str | None:
        if self.actor_role == "checker":
            return self.checker_principal_ref
        return self.maker_principal_ref


@dataclass(frozen=True)
class MonitorBinding:
    """One authorized telemetry scope the deployment has granted to the app.

    ``strategy_ref`` is the authorized producer identity this scope is allowed
    to observe.  It is supplied by the composition root, never derived from the
    scope reference or from the producer's own claim.
    """

    mount: str
    scope_ref: str
    strategy_ref: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.mount, "INVALID_MOUNT"),
            (self.scope_ref, "INVALID_SCOPE_REF"),
            (self.strategy_ref, "INVALID_STRATEGY_REF"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ServiceReadContractError(code)


class AuthorizedServiceReadClient:
    """Read authorized account and strategy-health views through one runtime.

    The runtime is borrowed: it is created and owned by the application's
    composition root, which is also responsible for closing it.  This adapter
    creates no thread and performs no I/O until one of its read methods runs.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        account_bindings: Mapping[str, AccountBinding],
        account_book_bindings: Mapping[str, AccountBookBinding] | None = None,
        monitor_bindings: Mapping[str, MonitorBinding] | None = None,
        order_bindings: Mapping[str, OrderBinding] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if runtime is None:
            raise ServiceReadContractError("INVALID_RUNTIME")
        if not callable(clock):
            raise ServiceReadContractError("INVALID_CLOCK")
        if not isinstance(account_bindings, Mapping):
            raise ServiceReadContractError("INVALID_ACCOUNT_BINDINGS")
        for account_ref, binding in account_bindings.items():
            if type(account_ref) is not str or not account_ref:
                raise ServiceReadContractError("INVALID_ACCOUNT_REF")
            if not isinstance(binding, AccountBinding):
                raise ServiceReadContractError("INVALID_ACCOUNT_BINDING")
        account_book_map: dict[str, AccountBookBinding] = {}
        for account_ref, binding in dict(account_book_bindings or {}).items():
            if type(account_ref) is not str or not account_ref:
                raise ServiceReadContractError("INVALID_ACCOUNT_REF")
            if not isinstance(binding, AccountBookBinding):
                raise ServiceReadContractError("INVALID_ACCOUNT_BOOK_BINDING")
            snapshot_binding = account_bindings.get(account_ref)
            if snapshot_binding is not None and (
                snapshot_binding.account_key.account_key_id != binding.account_key.account_key_id
            ):
                raise ServiceReadContractError("ACCOUNT_BOOK_KEY_MISMATCH")
            account_book_map[account_ref] = binding
        monitor_map: dict[str, MonitorBinding] = {}
        for scope_ref, binding in dict(monitor_bindings or {}).items():
            if type(scope_ref) is not str or not scope_ref:
                raise ServiceReadContractError("INVALID_SCOPE_REF")
            if not isinstance(binding, MonitorBinding):
                raise ServiceReadContractError("INVALID_MONITOR_BINDING")
            monitor_map[scope_ref] = binding

        order_map: dict[str, OrderBinding] = {}
        for scope_ref, binding in dict(order_bindings or {}).items():
            if type(scope_ref) is not str or not scope_ref:
                raise ServiceReadContractError("INVALID_SCOPE_REF")
            if not isinstance(binding, OrderBinding):
                raise ServiceReadContractError("INVALID_ORDER_BINDING")
            order_map[scope_ref] = binding

        self._runtime = runtime
        self._account_bindings = dict(account_bindings)
        self._account_book_bindings = account_book_map
        self._monitor_bindings = monitor_map
        self._order_bindings = order_map
        self._clock = clock
        self._account_clients: dict[str, Any] = {}
        self._closed = False
        self._close_failures: list[BaseException] = []

    @property
    def close_failures(self) -> tuple[BaseException, ...]:
        """Return original facade-close exceptions retained across retries."""

        return tuple(self._close_failures)

    def close(self) -> None:
        """Permanently close this adapter and every cached account facade.

        The runtime is borrowed and is never closed here. Closing is permanent
        even if one facade fails, so subsequent reads fail closed; a later
        ``close()`` retries only the facades that did not close successfully.
        """

        self._closed = True
        failures: list[BaseException] = []
        for account_ref, client in tuple(self._account_clients.items()):
            closer = getattr(client, "close", None)
            if not callable(closer):
                failures.append(RuntimeError("SERVICE_ACCOUNT_CLOSE_UNAVAILABLE"))
                continue
            try:
                closer()
            except BaseException as error:  # continue closing independent facades
                failures.append(error)
                continue
            if self._account_clients.get(account_ref) is client:
                del self._account_clients[account_ref]
        self._close_failures.extend(failures)
        if failures:
            error = ServiceReadClientCloseError(tuple(failures))
            raise error from failures[0]

    def _require_open(self) -> None:
        if self._closed:
            raise ServiceReadUnavailableError("SERVICE_READ_CLOSED")

    # -- account ------------------------------------------------------------

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        """Return the authorized account view for one configured account.

        A refused or unknown account raises :class:`ServiceReadUnavailableError`
        so a page cannot render a placeholder.  A transport-level failure
        returns an explicit ``unavailable`` view: the fact exists but could not
        be read now.
        """

        self._require_open()
        binding = self._account_bindings.get(account_ref)
        if binding is None:
            raise ServiceReadUnavailableError("ACCOUNT_NOT_CONFIGURED")
        requested_currency = currency or binding.currency
        if type(requested_currency) is not str or not requested_currency:
            raise ServiceReadContractError("INVALID_CURRENCY")

        client = self._account_client(account_ref, binding)
        try:
            state = client.refresh()
        except ServiceReadUnavailableError:
            raise
        except Exception as error:  # noqa: BLE001 - mapped to a finite view
            return self._degraded_account_view(account_ref, binding, requested_currency, error)
        return self._account_view(account_ref, requested_currency, state)

    def read_account_book(self, account_ref: str) -> AccountBookReadView:
        """Read one trusted account-book projection through the opted-in SDK op."""

        self._require_open()
        binding = self._account_book_bindings.get(account_ref)
        if binding is None:
            raise ServiceReadUnavailableError("ACCOUNT_BOOK_NOT_CONFIGURED")
        try:
            payload = self._runtime.call(
                binding.mount,
                "execution.account_books.query",
                {},
                scope_ref=binding.scope_ref,
            )
        except Exception as error:  # noqa: BLE001 - mapped to finite read diagnostics
            code = _error_code(error)
            if code in _REFUSAL_CODES:
                raise ServiceReadUnavailableError(code) from None
            raise ServiceReadUnavailableError(code) from None
        return _account_book_view(
            payload,
            account_ref,
            binding.account_key.account_key_id,
        )

    def _account_client(self, account_ref: str, binding: AccountBinding) -> Any:
        client = self._account_clients.get(account_ref)
        if client is not None:
            return client
        service_account = _service_account_module()
        try:
            client = service_account.ServiceAccountClient(
                self._runtime,
                binding.mount,
                account_ref=account_ref,
                expected_account=binding.account_key,
                required_coverage=binding.coverage,
                require_open_orders=binding.require_open_orders,
                expected_scope_ref=binding.scope_ref,
            )
        except Exception as error:  # noqa: BLE001 - configuration misuse
            raise ServiceReadUnavailableError(_error_code(error)) from None
        self._account_clients[account_ref] = client
        return client

    def _account_view(self, account_ref: str, currency: str, state: Any) -> AccountReadView:
        observation = getattr(state, "observation", None)
        if observation is None:
            return AccountReadView.unavailable(
                account_ref,
                _execution_domain_ref(None),
                currency,
                "ACCOUNT_OBSERVATION_MISSING",
            )
        provider_observation = _provider_observation_projection(observation)
        fresh_until = getattr(state, "fresh_until_monotonic", None)
        now = self._clock()
        quality = ReadQuality.STALE
        if isinstance(fresh_until, (int, float)) and now <= float(fresh_until):
            quality = ReadQuality.FRESH
        account_key, account_key_id = _account_key_identity(observation)
        cash, value, observed_at = _valuation_for(observation, currency)
        if cash is None and value is None and quality is ReadQuality.FRESH:
            # A current observation that carries no figure for this currency is
            # reported as not collected rather than as a zero balance.
            return AccountReadView(
                account_ref=account_ref,
                execution_domain_ref=_execution_domain_ref(observation),
                currency=currency,
                quality=ReadQuality.NOT_COLLECTED,
                source_service_id=None,
                session_generation=_text_or_none(getattr(state, "session_generation", None)),
                cursor=_int_or_none(getattr(state, "cursor", None)),
                detail_code="CURRENCY_NOT_OBSERVED",
                positions_count=_count(getattr(observation, "positions", None)),
                open_orders_count=_count(getattr(observation, "open_orders", None)),
                account_key=account_key,
                account_key_id=account_key_id,
                provider_observation=provider_observation,
            )
        return AccountReadView(
            account_ref=account_ref,
            execution_domain_ref=_execution_domain_ref(observation),
            currency=currency,
            quality=quality,
            session_generation=_text_or_none(getattr(state, "session_generation", None)),
            cursor=_int_or_none(getattr(state, "cursor", None)),
            cash=cash,
            value=value,
            observed_at_utc=observed_at,
            received_age_seconds=_age(now, getattr(state, "received_at_monotonic", None)),
            fresh_for_seconds=_age(fresh_until, now),
            positions_count=_count(getattr(observation, "positions", None)),
            open_orders_count=_count(getattr(observation, "open_orders", None)),
            account_key=account_key,
            account_key_id=account_key_id,
            provider_observation=provider_observation,
        )

    def _degraded_account_view(
        self, account_ref: str, binding: AccountBinding, currency: str, error: BaseException
    ) -> AccountReadView:
        code = _error_code(error)
        if code in _REFUSAL_CODES:
            raise ServiceReadUnavailableError(code) from None
        return AccountReadView.unavailable(
            account_ref,
            _execution_domain_ref(None),
            currency,
            code,
        )

    # -- managed orders -----------------------------------------------------

    def read_order(self, scope_ref: str, intent_id: str) -> OrderReadView:
        """Return the authorized durable record for one managed order.

        This never dispatches or cancels: it asks the journal what it already
        holds.  An unknown scope is a refusal; an unreadable record is an
        explicit unavailable view rather than a fabricated state.
        """

        self._require_open()
        binding = self._order_bindings.get(scope_ref)
        if binding is None:
            raise ServiceReadUnavailableError("SCOPE_NOT_CONFIGURED")
        if type(intent_id) is not str or not intent_id or intent_id != intent_id.strip():
            raise ServiceReadContractError("INVALID_INTENT_ID")
        try:
            payload = self._runtime.call(
                binding.mount,
                "orders.query",
                {"intent_id": intent_id},
                scope_ref=binding.scope_ref,
            )
        except Exception as error:  # noqa: BLE001 - mapped to a finite view
            code = _error_code(error)
            if code in _REFUSAL_CODES:
                raise ServiceReadUnavailableError(code) from None
            return OrderReadView.unavailable(intent_id, code)
        return _order_view(payload, intent_id)

    # -- strategy health ----------------------------------------------------

    def read_strategy_health(self, scope_ref: str) -> StrategyHealthView:
        """Return the authorized heartbeat view for one telemetry scope."""

        self._require_open()
        binding = self._monitor_bindings.get(scope_ref)
        if binding is None:
            raise ServiceReadUnavailableError("SCOPE_NOT_CONFIGURED")
        try:
            payload = self._runtime.call(
                binding.mount,
                "telemetry.snapshot",
                {},
                scope_ref=binding.scope_ref,
            )
        except Exception as error:  # noqa: BLE001 - mapped to a finite view
            code = _error_code(error)
            if code in _REFUSAL_CODES:
                raise ServiceReadUnavailableError(code) from None
            return StrategyHealthView.unavailable(binding.strategy_ref, scope_ref, code)
        return _strategy_health_view(payload, scope_ref, binding.strategy_ref)


# -- snapshot parsing -------------------------------------------------------


def _account_book_view(
    payload: Any,
    account_ref: str,
    account_key_id: str,
) -> AccountBookReadView:
    if not isinstance(payload, Mapping) or set(payload) != {"ok", "code", "result"}:
        raise ServiceReadUnavailableError("INVALID_ACCOUNT_BOOK_REPLY")
    code = payload.get("code")
    if payload.get("ok") is not True:
        if isinstance(code, str) and code in _REFUSAL_CODES:
            raise ServiceReadUnavailableError(code)
        raise ServiceReadUnavailableError("ACCOUNT_BOOK_READ_FAILED")
    if code != "OK" or not isinstance(payload.get("result"), Mapping):
        raise ServiceReadUnavailableError("INVALID_ACCOUNT_BOOK_REPLY")
    try:
        return AccountBookReadView(account_ref, account_key_id, payload["result"])
    except ServiceReadContractError as error:
        raise ServiceReadUnavailableError(error.code) from None


def _order_view(payload: Any, intent_id: str) -> OrderReadView:
    if not isinstance(payload, Mapping):
        raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    if set(payload) == {"ok", "code", "result"}:
        # The registry returns a handler's own reply as the call result, so a
        # business refusal arrives here as a nested envelope.
        code = payload.get("code")
        if payload.get("ok") is not True:
            if isinstance(code, str) and code in _REFUSAL_CODES:
                raise ServiceReadUnavailableError(code) from None
            return OrderReadView.unavailable(
                intent_id, code if isinstance(code, str) and code else "SERVICE_READ_FAILED"
            )
        payload = payload.get("result")
        if not isinstance(payload, Mapping):
            raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    if set(payload) != {"found", "record"}:
        raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    if payload.get("found") is False:
        return OrderReadView.not_collected(intent_id)
    if payload.get("found") is not True:
        raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    record = payload.get("record")
    if not isinstance(record, Mapping):
        raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    if record.get("intent_id") != intent_id:
        raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    state = record.get("state")
    if type(state) is not str or not state:
        raise ServiceReadUnavailableError("INVALID_ORDER_REPLY")
    return OrderReadView(
        intent_id=intent_id,
        quality=ReadQuality.FRESH,
        state=state,
        provider_order_id=_text_or_none(record.get("provider_order_id")),
        filled_quantity=_decimal_or_none(record.get("filled_quantity")),
        average_price=_decimal_or_none(record.get("average_price")),
        cumulative_commission=_decimal_or_none(record.get("cumulative_commission")),
        is_terminal=_bool_or_none(record.get("is_terminal")),
        unknown_reason=_text_or_none(record.get("unknown_reason")),
        review_required=_bool_or_none(record.get("review_required")),
        updated_at_ns=_int_or_none(record.get("updated_at_ns")),
    )


def _bool_or_none(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _strategy_health_view(payload: Any, scope_ref: str, strategy_ref: str) -> StrategyHealthView:
    if not isinstance(payload, Mapping) or set(payload) != _SNAPSHOT_FIELDS:
        raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
    streams = payload.get("streams")
    if not isinstance(streams, (list, tuple)):
        raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
    if payload.get("state") == "not_collected" and not streams:
        return StrategyHealthView.not_collected(strategy_ref, scope_ref)

    selected: Mapping[str, Any] | None = None
    for stream in streams:
        if not isinstance(stream, Mapping) or set(stream) != _STREAM_FIELDS:
            raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
        scope = stream.get("scope")
        if not isinstance(scope, Mapping):
            raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
        if scope.get("strategy_ref") != strategy_ref:
            continue
        if selected is not None:
            raise ServiceReadUnavailableError("AMBIGUOUS_STREAM")
        selected = stream
    if selected is None:
        return StrategyHealthView.not_collected(strategy_ref, scope_ref)

    status = selected.get("status")
    if status == "fresh":
        quality = ReadQuality.FRESH
    elif status == "stale":
        quality = ReadQuality.STALE
    elif status == "not_collected":
        return StrategyHealthView.not_collected(strategy_ref, scope_ref)
    else:
        raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
    return StrategyHealthView(
        strategy_ref=strategy_ref,
        scope_ref=scope_ref,
        quality=quality,
        stream_id=_text_or_none(selected.get("stream_id")),
        sequence=_int_or_none(selected.get("sequence")),
        heartbeat_age_seconds=_float_or_none(selected.get("heartbeat_age_seconds")),
        metrics_age_seconds=_float_or_none(selected.get("metrics_age_seconds")),
        metrics=_flat_metrics(selected.get("metrics")),
    )


def _flat_metrics(sample: Any) -> dict[str, float]:
    if sample is None:
        return {}
    if not isinstance(sample, Mapping):
        raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
    metrics = sample.get("metrics")
    if metrics is None:
        return {}
    if not isinstance(metrics, Mapping):
        raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
    normalized: dict[str, float] = {}
    for name, value in metrics.items():
        if type(name) is not str or not name or len(name) > _METRIC_NAME_LIMIT:
            raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
        number = float(value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ServiceReadUnavailableError("INVALID_SNAPSHOT")
        normalized[name] = number
    return normalized


def _valuation_for(
    observation: Any, currency: str
) -> tuple[Decimal | None, Decimal | None, str | None]:
    valuation = getattr(observation, "valuation", None)
    if valuation is not None and getattr(valuation, "currency", None) == currency:
        cash = _decimal_or_none(getattr(valuation, "available_cash", None))
        equity = _decimal_or_none(getattr(valuation, "equity", None))
        observed_at = _text_or_none(getattr(valuation, "observed_at_utc", None))
        if cash is not None or equity is not None:
            return cash, equity, observed_at
    for balance in getattr(observation, "balances", ()) or ():
        if getattr(balance, "currency", None) != currency:
            continue
        total = _decimal_or_none(getattr(balance, "total", None))
        available = _decimal_or_none(getattr(balance, "available", None))
        observed_at = _text_or_none(getattr(balance, "observed_at_utc", None))
        if total is not None or available is not None:
            return available, total, observed_at
    return None, None, None


def _provider_observation_projection(observation: Any) -> Mapping[str, Any] | None:
    """Copy only the public provider account facts from an authorized SDK view."""

    to_dict = getattr(observation, "to_dict", None)
    if not callable(to_dict):
        return None
    raw = to_dict()
    if not isinstance(raw, Mapping):
        raise ServiceReadContractError("INVALID_PROVIDER_ACCOUNT_OBSERVATION")
    fields = (
        "observation_id",
        "coverage",
        "balances",
        "positions",
        "valuation",
        "started_at_utc",
        "completed_at_utc",
        "consistency",
        "balances_complete",
        "positions_complete",
    )
    return {name: raw[name] for name in fields if name in raw}


def _execution_domain_ref(observation: Any) -> str:
    key = getattr(observation, "account_key", None)
    environment = getattr(key, "environment", None)
    venue = getattr(key, "venue", None)
    if isinstance(environment, str) and isinstance(venue, str) and environment and venue:
        return f"{environment}:{venue}"
    return "unresolved"


def _account_key_identity(observation: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Preserve the complete SDK key and its base-generated stable identity."""

    key = getattr(observation, "account_key", None)
    if key is None:
        return None, None
    try:
        from bt_api_base.account_protocol import AccountKey

        if type(key) is not AccountKey:
            return None, None
        raw = key.to_dict()
        identity = key.account_key_id
        if type(raw) is not dict or type(identity) is not str:
            return None, None
        return dict(raw), identity
    except Exception:  # noqa: BLE001 - keep optional SDK failures explicit as missing identity
        return None, None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception:  # noqa: BLE001 - unparsable provider figure
        return None
    return number if number.is_finite() else None


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return None if number != number or number in (float("inf"), float("-inf")) else number


def _age(now: float, then: Any) -> float | None:
    if not isinstance(then, (int, float)):
        return None
    return max(0.0, float(now) - float(then))


def _count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return len(value)
    except TypeError:
        return None


def _error_code(error: BaseException) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code and code.isascii() and len(code) <= 64:
        return code
    return "SERVICE_READ_FAILED"


def _service_account_module() -> Any:
    """Import the optional SDK facade only when a read is actually attempted."""

    try:
        from bt_api_py import service_account
    except Exception:  # noqa: BLE001 - optional dependency
        raise ServiceReadUnavailableError("SDK_NOT_INSTALLED") from None
    return service_account
