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

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.service_read.contracts import (
    AccountReadView,
    ReadQuality,
    ServiceReadContractError,
    StrategyHealthView,
)

__all__ = [
    "AccountBinding",
    "AuthorizedServiceReadClient",
    "MonitorBinding",
    "ServiceReadUnavailableError",
]


class ServiceReadUnavailableError(RuntimeError):
    """The authorized read path refused or could not answer this request.

    ``code`` is a finite diagnostic.  Callers must surface it instead of
    projecting a placeholder balance or health value.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


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
        monitor_bindings: Mapping[str, MonitorBinding] | None = None,
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
        monitor_map: dict[str, MonitorBinding] = {}
        for scope_ref, binding in dict(monitor_bindings or {}).items():
            if type(scope_ref) is not str or not scope_ref:
                raise ServiceReadContractError("INVALID_SCOPE_REF")
            if not isinstance(binding, MonitorBinding):
                raise ServiceReadContractError("INVALID_MONITOR_BINDING")
            monitor_map[scope_ref] = binding

        self._runtime = runtime
        self._account_bindings = dict(account_bindings)
        self._monitor_bindings = monitor_map
        self._clock = clock
        self._account_clients: dict[str, Any] = {}

    # -- account ------------------------------------------------------------

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        """Return the authorized account view for one configured account.

        A refused or unknown account raises :class:`ServiceReadUnavailableError`
        so a page cannot render a placeholder.  A transport-level failure
        returns an explicit ``unavailable`` view: the fact exists but could not
        be read now.
        """

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
        fresh_until = getattr(state, "fresh_until_monotonic", None)
        now = self._clock()
        quality = ReadQuality.STALE
        if isinstance(fresh_until, (int, float)) and now <= float(fresh_until):
            quality = ReadQuality.FRESH
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

    # -- strategy health ----------------------------------------------------

    def read_strategy_health(self, scope_ref: str) -> StrategyHealthView:
        """Return the authorized heartbeat view for one telemetry scope."""

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


def _execution_domain_ref(observation: Any) -> str:
    key = getattr(observation, "account_key", None)
    environment = getattr(key, "environment", None)
    venue = getattr(key, "venue", None)
    if isinstance(environment, str) and isinstance(venue, str) and environment and venue:
        return f"{environment}:{venue}"
    return "unresolved"


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
