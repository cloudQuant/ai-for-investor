"""Offline evidence for the application's authorized service read adapters.

These tests run without any service process.  They prove the boundary the
migration depends on: the application imports no domain package, constructs no
runtime on its own, never turns an absent fact into a zero, and reports a
refusal differently from a degraded read.
"""

import sys
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.service_read.client import (
    AccountBinding,
    AuthorizedServiceReadClient,
    MonitorBinding,
    OrderBinding,
    ServiceReadUnavailableError,
)
from app.services.service_read.consumers import (
    CONSUMERS,
    ConsumerRegistryError,
    ServiceConsumer,
    consumer_for,
    validate_consumers,
)
from app.services.service_read.contracts import (
    AccountReadView,
    OrderReadView,
    ReadQuality,
    ServiceReadContractError,
    StrategyHealthView,
)

_DOMAIN_PACKAGES = (
    "bt_api_gateway",
    "bt_api_monitor",
    "bt_api_risk",
    "bt_api_execution",
)


class _FakeState:
    def __init__(self, **overrides):
        self.observation = overrides.get("observation", _Observation())
        self.cursor = overrides.get("cursor", 7)
        self.snapshot_id = overrides.get("snapshot_id", "snapshot-1")
        self.session_generation = overrides.get("session_generation", "session-1")
        self.received_at_monotonic = overrides.get("received_at_monotonic", 100.0)
        self.fresh_until_monotonic = overrides.get("fresh_until_monotonic", 200.0)


class _Observation:
    def __init__(
        self, *, currency="USD", available="80", equity="105", balances=None, positions=None
    ):
        self.account_key = _AccountKey()
        self.valuation = _Valuation(currency, available, equity) if currency else None
        self.balances = tuple(balances or ())
        self.positions = tuple(positions or [])
        self.open_orders = ()


class _AccountKey:
    environment = "paper"
    venue = "simulated"


class _Valuation:
    def __init__(self, currency, available, equity):
        self.currency = currency
        self.available_cash = available
        self.equity = equity
        self.observed_at_utc = "2026-10-14T00:00:00Z"


class _FakeAccountClient:
    def __init__(self, state=None, error=None):
        self.state = state
        self.error = error
        self.calls = 0

    def refresh(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.state


class _StubError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class _FakeRuntime:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def call(self, mount, operation, arguments, scope_ref=None):
        self.calls.append((mount, operation, dict(arguments), scope_ref))
        if self.error is not None:
            raise self.error
        return self.payload


def _binding(**overrides):
    arguments = {
        "mount": "application.account",
        "scope_ref": "account-a-read-v1",
        "currency": "USD",
        "account_key": object(),
        "coverage": (object(),),
    }
    arguments.update(overrides)
    return AccountBinding(**arguments)


def _snapshot(metrics=None, status="fresh", strategy_ref="strategy-a"):
    return {
        "state": "collected",
        "streams": [
            {
                "producer": {
                    "role": "strategy_client",
                    "principal_ref": "principal-a",
                    "actor_ref": "strategy-a",
                    "delegate_ref": None,
                },
                "scope": {
                    "execution_domain_ref": "paper:demo",
                    "account_ref": None,
                    "account_refs": [],
                    "strategy_ref": strategy_ref,
                    "run_id": "run-1",
                    "manual_book_ref": None,
                    "portfolio_ref": None,
                    "group_id": None,
                    "leg_id": None,
                },
                "stream_id": "stream-1",
                "sequence": 4,
                "status": status,
                "received_age_seconds": 1.0,
                "heartbeat_age_seconds": 1.0,
                "heartbeat": {"metrics": {}},
                "metrics_age_seconds": 2.0,
                "metrics": {"metrics": dict(metrics or {"cpu_pct": 12.5})},
            }
        ],
    }


_ISOLATION_SCRIPT = """
import importlib.abc, sys
sys.path.insert(0, {backend_root!r})
BLOCKED = {blocked!r}
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == n or fullname.startswith(n + ".") for n in BLOCKED):
            raise AssertionError("blocked import: " + fullname)
        return None
sys.meta_path.insert(0, Blocker())
import app.services.service_read  # noqa: F401
import app.api.service_read  # noqa: F401
loaded = sorted(n for n in sys.modules if any(n == b or n.startswith(b + ".") for b in BLOCKED))
assert not loaded, loaded
print("isolated")
"""


def test_importing_the_application_read_path_loads_no_domain_package():
    """The check runs in a fresh interpreter so test order cannot mask it."""

    import subprocess

    backend_root = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _ISOLATION_SCRIPT.format(backend_root=backend_root, blocked=list(_DOMAIN_PACKAGES)),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "isolated" in result.stdout


def test_contracts_never_project_an_absent_fact_as_zero():
    view = AccountReadView.unavailable("account-a", "paper:simulated", "USD", "SERVICE_READ_FAILED")

    assert view.quality is ReadQuality.UNAVAILABLE
    assert view.cash is None and view.value is None
    assert view.has_current_facts is False
    with pytest.raises(ServiceReadContractError, match="ABSENT_VIEW_MUST_NOT_CARRY_VALUES"):
        AccountReadView(
            account_ref="account-a",
            execution_domain_ref="paper:simulated",
            currency="USD",
            quality=ReadQuality.UNAVAILABLE,
            cash=Decimal("0"),
        )
    with pytest.raises(ServiceReadContractError, match="NOT_COLLECTED_MUST_NOT_CARRY_METRICS"):
        StrategyHealthView(
            strategy_ref="strategy-a",
            scope_ref="scope-a",
            quality=ReadQuality.NOT_COLLECTED,
            metrics={"cpu_pct": 1.0},
        )


def test_health_is_proven_by_a_fresh_heartbeat_only():
    not_collected = StrategyHealthView.not_collected("strategy-a", "scope-a")
    stale = StrategyHealthView(
        strategy_ref="strategy-a",
        scope_ref="scope-a",
        quality=ReadQuality.STALE,
        heartbeat_age_seconds=90.0,
    )

    assert not_collected.is_healthy is False
    assert stale.is_healthy is False
    assert stale.metrics == {}


def test_consumer_registry_is_consistent_and_complete():
    consumers = validate_consumers()

    assert {consumer.consumer_id for consumer in consumers} == set(CONSUMERS)
    assert consumer_for("strategy-health").status == "read-migrated"
    assert consumer_for("manual-and-ai-orders").status == "pending"
    with pytest.raises(ConsumerRegistryError, match="UNKNOWN_CONSUMER"):
        consumer_for("not-registered")


def test_pending_consumers_may_not_claim_stronger_evidence():
    with pytest.raises(ConsumerRegistryError, match="PENDING_CONSUMER_MUST_BE_CONTRACT_ONLY"):
        ServiceConsumer(
            consumer_id="x",
            surface="GET /x",
            capability="service.account_read",
            status="pending",
            evidence="local-process",
            authority_owner="bt_api_gateway",
            notes="n",
        )
    with pytest.raises(ConsumerRegistryError, match="MIGRATED_CONSUMER_REQUIRES_EVIDENCE"):
        ServiceConsumer(
            consumer_id="x",
            surface="GET /x",
            capability="service.account_read",
            status="read-migrated",
            evidence="contract",
            authority_owner="bt_api_gateway",
            notes="n",
        )
    with pytest.raises(ConsumerRegistryError, match="UNKNOWN_CAPABILITY"):
        ServiceConsumer(
            consumer_id="x",
            surface="GET /x",
            capability="service.made_up",
            status="pending",
            evidence="contract",
            authority_owner="bt_api_gateway",
            notes="n",
        )


def test_account_read_projects_provider_facts_with_quality(monkeypatch):
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(
        runtime, account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    fake = _FakeAccountClient(state=_FakeState())
    monkeypatch.setattr(client, "_account_clients", {"account-a": fake})

    view = client.read_account("account-a")

    assert view.quality is ReadQuality.FRESH
    assert view.cash == Decimal("80")
    assert view.value == Decimal("105")
    assert view.execution_domain_ref == "paper:simulated"
    assert view.has_current_facts is True
    assert fake.calls == 1


def test_account_read_preserves_the_complete_sdk_account_key(monkeypatch):
    try:
        from bt_api_base.account_protocol import AccountKey
    except ImportError:
        pytest.skip("bt_api_base account protocol is not installed")

    sdk_key = AccountKey(
        provider="synthetic-provider",
        venue="synthetic-venue",
        environment="paper",
        account_id="account-7",
        subaccount_id="sub-2",
    )
    observation = _Observation()
    observation.account_key = sdk_key
    client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(state=_FakeState(observation=observation))},
    )

    view = client.read_account("account-a")

    assert dict(view.account_key) == sdk_key.to_dict()
    assert view.account_key_id == sdk_key.account_key_id
    assert view.provider_observation is None


def test_account_read_projects_authorized_provider_observation_without_filling_missing_facts(
    monkeypatch,
):
    try:
        from bt_api_base.account_protocol import (
            AccountBalance,
            AccountKey,
            AccountObservation,
            AccountPosition,
            AccountResourceKey,
            AccountValuation,
        )
        from bt_api_base.market_protocol import MarketInstrumentKey
    except ImportError:
        pytest.skip("bt_api_base account protocol is not installed")

    sdk_key = AccountKey(
        provider="synthetic-provider",
        venue="synthetic-venue",
        environment="paper",
        account_id="synthetic-private-account",
        subaccount_id=None,
    )
    spot = AccountResourceKey(product_type="SPOT", margin_pool="cash")
    zero_instrument = MarketInstrumentKey(
        provider=sdk_key.provider,
        venue=sdk_key.venue,
        environment=sdk_key.environment,
        product_type="SPOT",
        instrument_id="instrument-zero",
        native_symbol="ZERO/EUR",
    )
    missing_instrument = MarketInstrumentKey(
        provider=sdk_key.provider,
        venue=sdk_key.venue,
        environment=sdk_key.environment,
        product_type="SPOT",
        instrument_id="instrument-missing",
        native_symbol="MISSING/EUR",
    )
    observation = AccountObservation(
        account_key=sdk_key,
        observation_id="synthetic-observation-1",
        coverage=(spot,),
        balances=(
            AccountBalance(
                resource=spot,
                currency="USD",
                total="0",
                available="0",
                locked="0",
                observed_at_utc="2026-10-15T00:00:00Z",
            ),
            AccountBalance(
                resource=spot,
                currency="EUR",
                total="12.5",
                available=None,
                locked="0",
                observed_at_utc="2026-10-15T00:00:00.5Z",
            ),
        ),
        positions=(
            AccountPosition(
                resource=spot,
                instrument=zero_instrument,
                side="net",
                quantity="0",
                qty_unit="base_asset",
                average_price="0",
                price_currency="EUR",
                observed_at_utc="2026-10-15T00:00:00Z",
            ),
            AccountPosition(
                resource=spot,
                instrument=missing_instrument,
                side="long",
                quantity="2",
                qty_unit="contracts",
                average_price=None,
                price_currency=None,
                observed_at_utc="2026-10-15T00:00:01Z",
            ),
        ),
        valuation=AccountValuation(
            currency="USD",
            available_cash="0",
            equity=None,
            observed_at_utc="2026-10-15T00:00:01Z",
        ),
        started_at_utc="2026-10-15T00:00:00Z",
        completed_at_utc="2026-10-15T00:00:02Z",
        consistency="multi_query",
        balances_complete=False,
        positions_complete=True,
    )

    fresh_client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    monkeypatch.setattr(
        fresh_client,
        "_account_clients",
        {"account-a": _FakeAccountClient(state=_FakeState(observation=observation))},
    )
    fresh_view = fresh_client.read_account("account-a")

    assert fresh_view.quality is ReadQuality.FRESH
    projected = fresh_view.provider_observation
    assert projected is not None
    assert projected["observation_id"] == "synthetic-observation-1"
    assert projected["balances"][0]["total"] == "0"
    assert projected["balances"][1]["total"] == "12.5"
    assert projected["balances"][1]["available"] is None
    assert projected["positions"][0]["quantity"] == "0"
    assert projected["positions"][0]["average_price"] == "0"
    assert projected["positions"][1]["quantity"] == "2"
    assert projected["positions"][1]["average_price"] is None
    assert projected["positions"][1]["qty_unit"] == "contracts"
    assert projected["balances_complete"] is False
    assert projected["positions_complete"] is True
    assert "account_key" not in projected

    uncollected_view = fresh_client.read_account("account-a", currency="JPY")
    assert uncollected_view.quality is ReadQuality.NOT_COLLECTED
    assert uncollected_view.cash is None and uncollected_view.value is None
    assert uncollected_view.provider_observation is not None
    assert uncollected_view.detail_code == "CURRENCY_NOT_OBSERVED"

    stale_client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 500.0
    )
    monkeypatch.setattr(
        stale_client,
        "_account_clients",
        {
            "account-a": _FakeAccountClient(
                state=_FakeState(observation=observation, fresh_until_monotonic=200.0)
            )
        },
    )
    stale_view = stale_client.read_account("account-a")
    assert stale_view.quality is ReadQuality.STALE
    assert stale_view.cash == Decimal("0")
    assert stale_view.provider_observation is not None
    assert stale_view.provider_observation["positions"][1]["average_price"] is None

    class _MalformedObservation:
        def __init__(self, account_key):
            self.account_key = account_key
            self.valuation = None
            self.balances = ()
            self.positions = ()
            self.open_orders = ()

        def to_dict(self):
            return {"observation_id": "malformed"}

    malformed_client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    monkeypatch.setattr(
        malformed_client,
        "_account_clients",
        {
            "account-a": _FakeAccountClient(
                state=_FakeState(observation=_MalformedObservation(sdk_key))
            )
        },
    )
    with pytest.raises(ServiceReadContractError, match="INVALID_PROVIDER_ACCOUNT_OBSERVATION"):
        malformed_client.read_account("account-a")


def test_stale_observation_keeps_its_figures_but_is_not_current(monkeypatch):
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(
        runtime, account_bindings={"account-a": _binding()}, clock=lambda: 500.0
    )
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(state=_FakeState(fresh_until_monotonic=200.0))},
    )

    view = client.read_account("account-a")

    assert view.quality is ReadQuality.STALE
    assert view.cash == Decimal("80")
    assert view.has_current_facts is False


def test_observation_without_the_requested_currency_is_not_collected(monkeypatch):
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(
        runtime, account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    monkeypatch.setattr(
        client,
        "_account_clients",
        {
            "account-a": _FakeAccountClient(
                state=_FakeState(observation=_Observation(currency=None))
            )
        },
    )

    view = client.read_account("account-a", currency="EUR")

    assert view.quality is ReadQuality.NOT_COLLECTED
    assert view.cash is None and view.value is None
    assert view.detail_code == "CURRENCY_NOT_OBSERVED"


def test_refused_scope_is_a_refusal_not_a_degraded_page(monkeypatch):
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(runtime, account_bindings={"account-a": _binding()})
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(error=_StubError("SCOPE_DENIED"))},
    )

    with pytest.raises(ServiceReadUnavailableError, match="SCOPE_DENIED"):
        client.read_account("account-a")


def test_transport_failure_degrades_explicitly(monkeypatch):
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(runtime, account_bindings={"account-a": _binding()})
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))},
    )

    view = client.read_account("account-a")

    assert view.quality is ReadQuality.UNAVAILABLE
    assert view.cash is None and view.value is None
    assert view.detail_code == "BUSINESS_OUTCOME_UNKNOWN"
    assert view.provider_observation is None


def test_unconfigured_account_is_refused_without_any_read():
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(runtime, account_bindings={})

    with pytest.raises(ServiceReadUnavailableError, match="ACCOUNT_NOT_CONFIGURED"):
        client.read_account("account-a")
    assert runtime.calls == []


def test_strategy_health_projects_the_authorized_snapshot():
    runtime = _FakeRuntime(payload=_snapshot(metrics={"cpu_pct": 12.5, "latency_ms": 7.0}))
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )

    view = client.read_strategy_health("scope-a")

    assert view.quality is ReadQuality.FRESH
    assert view.is_healthy is True
    assert view.sequence == 4
    assert view.metrics == {"cpu_pct": 12.5, "latency_ms": 7.0}
    assert runtime.calls == [("application.monitor", "telemetry.snapshot", {}, "scope-a")]


def test_stale_heartbeat_is_reported_as_stale_not_healthy():
    runtime = _FakeRuntime(payload=_snapshot(status="stale"))
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )

    view = client.read_strategy_health("scope-a")

    assert view.quality is ReadQuality.STALE
    assert view.is_healthy is False


def test_missing_stream_is_reported_as_not_collected():
    runtime = _FakeRuntime(payload={"state": "not_collected", "streams": []})
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )

    view = client.read_strategy_health("scope-a")

    assert view.quality is ReadQuality.NOT_COLLECTED
    assert view.is_healthy is False
    assert view.metrics == {}


def test_another_strategy_stream_is_not_mistaken_for_this_one():
    runtime = _FakeRuntime(payload=_snapshot(strategy_ref="strategy-b"))
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )

    view = client.read_strategy_health("scope-a")

    assert view.quality is ReadQuality.NOT_COLLECTED


def test_unknown_scope_is_refused_without_any_read():
    runtime = _FakeRuntime()
    client = AuthorizedServiceReadClient(runtime, account_bindings={})

    with pytest.raises(ServiceReadUnavailableError, match="SCOPE_NOT_CONFIGURED"):
        client.read_strategy_health("scope-a")
    assert runtime.calls == []


def test_malformed_snapshot_is_rejected():
    runtime = _FakeRuntime(payload={"state": "collected", "streams": [{"status": "fresh"}]})
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )

    with pytest.raises(ServiceReadUnavailableError, match="INVALID_SNAPSHOT"):
        client.read_strategy_health("scope-a")


def test_bindings_are_validated_at_construction():
    runtime = _FakeRuntime()
    with pytest.raises(ServiceReadContractError, match="INVALID_RUNTIME"):
        AuthorizedServiceReadClient(None, account_bindings={})
    with pytest.raises(ServiceReadContractError, match="INVALID_ACCOUNT_BINDING"):
        AuthorizedServiceReadClient(runtime, account_bindings={"account-a": object()})
    with pytest.raises(ServiceReadContractError, match="INVALID_MONITOR_BINDING"):
        AuthorizedServiceReadClient(
            runtime, account_bindings={}, monitor_bindings={"scope-a": object()}
        )
    with pytest.raises(ServiceReadContractError, match="INVALID_COVERAGE"):
        _binding(coverage=())


def _order_record(**overrides):
    record = {
        "intent_id": "intent-1",
        "scope_key": "scope:abc",
        "payload_sha256": "0" * 64,
        "state": "ACKED",
        "provider_order_id": "provider-order-1",
        "filled_quantity": "0",
        "average_price": None,
        "cumulative_commission": None,
        "permit_reference": "permit-1",
        "dispatch_attempts": 1,
        "unknown_reason": None,
        "review_required": False,
        "created_at_ns": 1,
        "updated_at_ns": 9,
        "is_terminal": False,
    }
    record.update(overrides)
    return record


def _order_client(payload=None, error=None):
    runtime = _FakeRuntime(payload=payload, error=error)
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        order_bindings={"orders-a": OrderBinding("broker.order_query", "orders-a")},
    )
    return runtime, client


def test_order_read_projects_the_durable_record():
    runtime, client = _order_client(
        payload={
            "found": True,
            "record": _order_record(state="PARTIALLY_FILLED", filled_quantity="1.5"),
        }
    )

    view = client.read_order("orders-a", "intent-1")

    assert view.quality is ReadQuality.FRESH
    assert view.state == "PARTIALLY_FILLED"
    assert view.provider_order_id == "provider-order-1"
    assert view.filled_quantity == Decimal("1.5")
    assert view.is_unknown is False
    assert view.updated_at_ns == 9
    assert runtime.calls == [
        ("broker.order_query", "orders.query", {"intent_id": "intent-1"}, "orders-a")
    ]


def test_order_read_reports_a_missing_record_without_a_state():
    _runtime, client = _order_client(payload={"found": False, "record": None})

    view = client.read_order("orders-a", "intent-1")

    assert view.quality is ReadQuality.NOT_COLLECTED
    assert view.state is None
    assert view.provider_order_id is None


def test_order_read_keeps_an_unknown_record_reconcilable():
    _runtime, client = _order_client(
        payload={
            "found": True,
            "record": _order_record(
                state="UNKNOWN", provider_order_id=None, unknown_reason="provider_timeout"
            ),
        }
    )

    view = client.read_order("orders-a", "intent-1")

    assert view.is_unknown is True
    assert view.unknown_reason == "provider_timeout"
    assert view.state == "UNKNOWN"


def test_order_read_degrades_explicitly_and_refuses_unauthorized_scope():
    _runtime, client = _order_client(error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))
    unavailable = client.read_order("orders-a", "intent-1")
    assert unavailable.quality is ReadQuality.UNAVAILABLE
    assert unavailable.state is None

    _runtime2, client2 = _order_client(error=_StubError("SCOPE_DENIED"))
    with pytest.raises(ServiceReadUnavailableError, match="SCOPE_DENIED"):
        client2.read_order("orders-a", "intent-1")

    with pytest.raises(ServiceReadUnavailableError, match="SCOPE_NOT_CONFIGURED"):
        client.read_order("orders-z", "intent-1")


def test_order_read_rejects_a_malformed_or_mismatched_reply():
    for payload in (
        {"found": True, "record": None},
        {"found": True, "record": _order_record(intent_id="intent-9")},
        {"found": True, "record": _order_record(state="")},
        {"found": True, "record": {"intent_id": "intent-1"}},
        {"record": None},
    ):
        _runtime, client = _order_client(payload=payload)
        with pytest.raises(ServiceReadUnavailableError, match="INVALID_ORDER_REPLY"):
            client.read_order("orders-a", "intent-1")


def test_order_view_refuses_a_state_without_a_quality():
    with pytest.raises(ServiceReadContractError, match="ABSENT_VIEW_MUST_NOT_CARRY_VALUES"):
        OrderReadView(intent_id="intent-1", quality=ReadQuality.UNAVAILABLE, state="ACKED")
    with pytest.raises(ServiceReadContractError, match="INVALID_STATE"):
        OrderReadView(intent_id="intent-1", quality=ReadQuality.FRESH, state="acked")


def test_order_bindings_are_validated_at_construction():
    runtime = _FakeRuntime()
    with pytest.raises(ServiceReadContractError, match="INVALID_ORDER_BINDING"):
        AuthorizedServiceReadClient(
            runtime, account_bindings={}, order_bindings={"orders-a": object()}
        )
    with pytest.raises(ServiceReadContractError, match="INVALID_SCOPE_REF"):
        AuthorizedServiceReadClient(
            runtime,
            account_bindings={},
            order_bindings={"": OrderBinding("broker.order_query", "x")},
        )


def test_order_consumer_is_registered_with_its_evidence():
    consumer = consumer_for("order-status")

    assert consumer.capability == "service.order_query"
    assert consumer.status == "read-migrated"
    assert consumer.evidence == "local-process"


def test_order_read_accepts_the_registry_wrapped_reply_envelope():
    """The real wire shape nests the handler reply inside the call result."""

    _runtime, client = _order_client(
        payload={
            "ok": True,
            "code": "OK",
            "result": {"found": True, "record": _order_record(state="ACKED")},
        }
    )

    assert client.read_order("orders-a", "intent-1").state == "ACKED"


def test_order_read_maps_a_wrapped_business_refusal_by_certainty():
    _runtime, refused = _order_client(
        payload={"ok": False, "code": "SCOPE_DENIED", "result": {"found": False, "record": None}}
    )
    with pytest.raises(ServiceReadUnavailableError, match="SCOPE_DENIED"):
        refused.read_order("orders-a", "intent-1")

    _runtime, degraded = _order_client(
        payload={"ok": False, "code": "HANDLER_FAILED", "result": {"found": False, "record": None}}
    )
    view = degraded.read_order("orders-a", "intent-1")
    assert view.quality is ReadQuality.UNAVAILABLE
    assert view.state is None
