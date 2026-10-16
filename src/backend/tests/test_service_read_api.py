"""HTTP-level evidence for the read-only service endpoints.

The full application cannot be imported in every environment, so these tests
mount the real router on a minimal FastAPI app and override only the
authentication dependency.  The router, its dependency wiring, the status
mapping and the real read adapter are exercised unchanged.
"""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.api.afi_owner_scope import PersistedOwnerScope, require_persisted_owner_scope
from app.api.deps import get_current_user
from app.api.service_read import configure_service_read, router
from app.schemas.auth import TokenPayload
from app.services.service_read.access import (
    ReadAccess,
    ServiceReadAccessDirectory,
    ServiceReadAccessError,
)
from app.services.service_read.client import (
    AccountBinding,
    AuthorizedServiceReadClient,
    MonitorBinding,
    OrderBinding,
)
from app.services.service_read.contracts import ReadQuality, StrategyHealthView
from tests.test_service_read_client import (
    _FakeAccountClient,
    _FakeRuntime,
    _FakeState,
    _Observation,
    _StubError,
)


def _app(*, authenticated=True, token=None):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if authenticated:
        current = token or TokenPayload(sub="test-user", username="tester")
        app.dependency_overrides[get_current_user] = lambda: current
        # These bare-router unit tests exercise the read projection and use
        # synthetic subjects. Persisted owner authorization is covered by the
        # separate HTTP integration test, so replace only that boundary here.
        app.dependency_overrides[require_persisted_owner_scope] = lambda: PersistedOwnerScope(
            owner_subject=current.sub,
            principal_kind="UNKNOWN",
        )
    return app


def _get(app, path, *, headers=None):
    async def _call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)

    return asyncio.run(_call())


class _AsyncClientWorker:
    """Route-facing async fake that delegates to the established read client."""

    def __init__(self, client):
        self.client = client
        self.calls = []

    async def read_account(self, account_ref, *, currency=None):
        self.calls.append(("account", account_ref, currency))
        return self.client.read_account(account_ref, currency=currency)

    async def read_order(self, scope_ref, intent_id):
        self.calls.append(("order", scope_ref, intent_id))
        return self.client.read_order(scope_ref, intent_id)

    async def read_strategy_health(self, scope_ref):
        self.calls.append(("monitor", scope_ref))
        return self.client.read_strategy_health(scope_ref)


def _configure_client(
    client,
    *,
    account_refs=(),
    order_scope_refs=(),
    monitor_scope_refs=(),
    subject="test-user",
):
    worker = _AsyncClientWorker(client)
    directory = ServiceReadAccessDirectory(
        {
            subject: ReadAccess(
                worker,
                allow_account_refs=frozenset(account_refs),
                allow_order_scope_refs=frozenset(order_scope_refs),
                allow_monitor_scope_refs=frozenset(monitor_scope_refs),
            )
        }
    )
    configure_service_read(directory)
    return worker


def _binding():
    return AccountBinding(
        mount="application.account",
        scope_ref="account-a-read-v1",
        currency="USD",
        account_key=object(),
        coverage=(object(),),
    )


@pytest.fixture(autouse=True)
def _reset_client():
    configure_service_read(None)
    yield
    configure_service_read(None)


def test_unauthenticated_request_is_rejected():
    app = _app(authenticated=False)

    response = _get(app, "/api/v1/service-read/consumers")

    assert response.status_code in (401, 403)


def test_without_a_configured_read_path_nothing_is_projected():
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SERVICE_READ_NOT_CONFIGURED"


def test_clearing_configuration_returns_the_routes_to_default_off():
    _configure_client(
        AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={}),
        account_refs={"account-a"},
    )
    configure_service_read(None)

    response = _get(_app(), "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SERVICE_READ_NOT_CONFIGURED"


def test_account_read_projects_quality_and_never_a_placeholder(monkeypatch):
    client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    monkeypatch.setattr(
        client, "_account_clients", {"account-a": _FakeAccountClient(state=_FakeState())}
    )
    _configure_client(client, account_refs={"account-a"})
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"] == "fresh"
    assert payload["has_current_facts"] is True
    assert payload["cash"] == "80"
    assert payload["value"] == "105"
    assert payload["execution_domain_ref"] == "paper:simulated"


def test_absent_currency_is_reported_as_nulls_with_an_explicit_marker(monkeypatch):
    client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 150.0
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
    _configure_client(client, account_refs={"account-a"})
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"] == "not_collected"
    assert payload["cash"] is None and payload["value"] is None
    assert payload["has_current_facts"] is False


def test_refused_scope_is_forbidden_rather_than_degraded(monkeypatch):
    client = AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={"account-a": _binding()})
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(error=_StubError("SCOPE_DENIED"))},
    )
    _configure_client(client, account_refs={"account-a"})
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"


def test_unregistered_account_is_not_found():
    _configure_client(
        AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={}),
        account_refs={"account-z"},
    )
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-z")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"


def test_transport_failure_is_reported_as_unavailable(monkeypatch):
    client = AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={"account-a": _binding()})
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))},
    )
    _configure_client(client, account_refs={"account-a"})
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"] == "unavailable"
    assert payload["cash"] is None
    assert payload["detail_code"] == "BUSINESS_OUTCOME_UNKNOWN"


def _snapshot(status="fresh"):
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
                    "strategy_ref": "strategy-a",
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
                "metrics": {"metrics": {"cpu_pct": 12.5}},
            }
        ],
    }


def test_strategy_health_reports_the_heartbeat_observation():
    client = AuthorizedServiceReadClient(
        _FakeRuntime(payload=_snapshot()),
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )
    _configure_client(client, monitor_scope_refs={"scope-a"})
    app = _app()

    response = _get(app, "/api/v1/service-read/strategy-health/scope-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"] == "fresh"
    assert payload["is_healthy"] is True
    assert payload["metrics"] == {"cpu_pct": 12.5}
    assert "not trading readiness" in payload["authority"]


def test_missing_heartbeat_is_not_reported_as_healthy():
    client = AuthorizedServiceReadClient(
        _FakeRuntime(payload={"state": "not_collected", "streams": []}),
        account_bindings={},
        monitor_bindings={
            "scope-a": MonitorBinding("application.monitor", "scope-a", "strategy-a")
        },
    )
    _configure_client(client, monitor_scope_refs={"scope-a"})
    app = _app()

    response = _get(app, "/api/v1/service-read/strategy-health/scope-a")

    assert response.status_code == 200
    assert response.json()["quality"] == "not_collected"
    assert response.json()["is_healthy"] is False


def test_consumer_registry_endpoint_lists_recorded_evidence():
    app = _app()

    response = _get(app, "/api/v1/service-read/consumers")

    assert response.status_code == 200
    payload = response.json()
    ids = {item["consumer_id"] for item in payload["consumers"]}
    assert "manual-and-ai-orders" in ids
    assert payload["migrated"] == ["order-status", "strategy-health"]


def test_health_view_without_a_bound_scope_is_refused():
    _configure_client(
        AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={}),
        monitor_scope_refs={"scope-z"},
    )
    app = _app()

    response = _get(app, "/api/v1/service-read/strategy-health/scope-z")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"


def test_neutral_views_keep_the_read_quality_enum():
    view = StrategyHealthView.not_collected("strategy-a", "scope-a")

    assert view.quality is ReadQuality.NOT_COLLECTED
    assert view.is_healthy is False


def _order_client(payload=None, error=None):
    from tests.test_service_read_client import _FakeRuntime, _order_record

    runtime = _FakeRuntime(payload=payload, error=error)
    client = AuthorizedServiceReadClient(
        runtime,
        account_bindings={},
        order_bindings={"orders-a": OrderBinding("application.order_query", "orders-a")},
    )
    del _order_record
    return client


def test_order_endpoint_projects_the_authorized_record():
    from tests.test_service_read_client import _order_record

    _configure_client(
        _order_client(
            payload={"found": True, "record": _order_record(state="ACKED")},
        ),
        order_scope_refs={"orders-a"},
    )
    app = _app()

    response = _get(app, "/api/v1/service-read/orders/intent-1?scope_ref=orders-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"] == "fresh"
    assert payload["state"] == "ACKED"
    assert payload["provider_order_id"] == "provider-order-1"
    assert payload["is_terminal"] is False
    assert "not a strategy ledger" in payload["authority"]


def test_order_endpoint_reports_a_missing_record_without_a_state():
    _configure_client(
        _order_client(payload={"found": False, "record": None}),
        order_scope_refs={"orders-a"},
    )
    app = _app()

    response = _get(app, "/api/v1/service-read/orders/intent-1?scope_ref=orders-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["quality"] == "not_collected"
    assert payload["state"] is None


def test_order_endpoint_refuses_an_ungranted_scope():
    _configure_client(
        _order_client(payload={"found": False, "record": None}),
        order_scope_refs={"orders-a"},
    )
    app = _app()

    response = _get(app, "/api/v1/service-read/orders/intent-1?scope_ref=orders-z")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"


def test_order_endpoint_maps_a_refusal_and_a_degraded_read():
    from tests.test_service_read_client import _StubError

    _configure_client(
        _order_client(error=_StubError("SCOPE_DENIED")),
        order_scope_refs={"orders-a"},
    )
    forbidden = _get(_app(), "/api/v1/service-read/orders/intent-1?scope_ref=orders-a")
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "SERVICE_READ_ACCESS_DENIED"

    _configure_client(
        _order_client(error=_StubError("BUSINESS_OUTCOME_UNKNOWN")),
        order_scope_refs={"orders-a"},
    )
    degraded = _get(_app(), "/api/v1/service-read/orders/intent-1?scope_ref=orders-a")
    assert degraded.status_code == 200
    payload = degraded.json()
    assert payload["quality"] == "unavailable"
    assert payload["state"] is None
    assert payload["detail_code"] == "BUSINESS_OUTCOME_UNKNOWN"


def test_order_endpoint_requires_a_configured_read_path():
    response = _get(_app(), "/api/v1/service-read/orders/intent-1?scope_ref=orders-a")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SERVICE_READ_NOT_CONFIGURED"


def test_configuration_rejects_a_shared_synchronous_client():
    client = AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={})

    with pytest.raises(ServiceReadAccessError) as error:
        configure_service_read(client)

    assert error.value.code == "INVALID_ACCESS_DIRECTORY"


def test_worker_lifecycle_failure_is_a_generic_unavailable_response():
    class FailedWorker:
        async def read_account(self, account_ref, *, currency=None):
            del account_ref, currency
            error = RuntimeError("private runtime details")
            error.code = "MAINTAIN_FAILED"
            raise error

        async def read_order(self, scope_ref, intent_id):
            del scope_ref, intent_id

        async def read_strategy_health(self, scope_ref):
            del scope_ref

    configure_service_read(
        ServiceReadAccessDirectory(
            {"test-user": ReadAccess(FailedWorker(), allow_account_refs={"account-a"})}
        )
    )
    response = _get(_app(), "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "MAINTAIN_FAILED"
    assert "private runtime details" not in response.text


def test_subjects_cannot_cross_read_each_others_account_order_or_health():
    alice_worker = _AsyncClientWorker(
        AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={})
    )
    bob_worker = _AsyncClientWorker(
        AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={})
    )
    configure_service_read(
        ServiceReadAccessDirectory(
            {
                "alice": ReadAccess(
                    alice_worker,
                    allow_account_refs={"account-a"},
                    allow_order_scope_refs={"orders-a"},
                    allow_monitor_scope_refs={"health-a"},
                ),
                "bob": ReadAccess(
                    bob_worker,
                    allow_account_refs={"account-b"},
                    allow_order_scope_refs={"orders-b"},
                    allow_monitor_scope_refs={"health-b"},
                ),
            }
        )
    )
    forged_headers = {
        "X-Actor-Ref": "alice",
        "X-Principal-Ref": "principal-a",
        "X-Delegate-Ref": "delegate-a",
        "X-User-Id": "alice",
        "X-Account-Ref": "account-a",
        "X-Scope-Ref": "orders-a",
    }
    cases = (
        (
            "alice",
            "/api/v1/service-read/accounts/account-b?actor_ref=alice&principal_ref=principal-a&user_id=alice",
        ),
        (
            "alice",
            "/api/v1/service-read/orders/intent-1?scope_ref=orders-b&actor_ref=alice&user_id=alice",
        ),
        ("alice", "/api/v1/service-read/strategy-health/health-b?actor_ref=alice&user_id=alice"),
        (
            "bob",
            "/api/v1/service-read/accounts/account-a?actor_ref=bob&principal_ref=principal-b&user_id=alice",
        ),
        (
            "bob",
            "/api/v1/service-read/orders/intent-1?scope_ref=orders-a&actor_ref=bob&user_id=alice",
        ),
        ("bob", "/api/v1/service-read/strategy-health/health-a?actor_ref=bob&user_id=alice"),
        ("mallory", "/api/v1/service-read/accounts/account-a?actor_ref=alice&user_id=alice"),
    )

    responses = []
    for subject, path in cases:
        token = TokenPayload(sub=subject, username=subject)
        responses.append(_get(_app(token=token), path, headers=forged_headers))

    assert [
        (response.status_code, response.json()["detail"]["code"]) for response in responses
    ] == [(403, "SERVICE_READ_ACCESS_DENIED")] * len(cases)
    assert alice_worker.calls == []
    assert bob_worker.calls == []
