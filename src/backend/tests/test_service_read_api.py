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

from app.api.deps import get_current_user
from app.api.service_read import configure_service_read, router
from app.services.service_read.client import (
    AccountBinding,
    AuthorizedServiceReadClient,
    MonitorBinding,
)
from app.services.service_read.contracts import ReadQuality, StrategyHealthView
from tests.test_service_read_client import (
    _FakeAccountClient,
    _FakeRuntime,
    _FakeState,
    _Observation,
    _StubError,
)


def _app(*, authenticated=True):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "test-user"}
    return app


def _get(app, path):
    async def _call():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)

    return asyncio.run(_call())


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


def test_account_read_projects_quality_and_never_a_placeholder(monkeypatch):
    client = AuthorizedServiceReadClient(
        _FakeRuntime(), account_bindings={"account-a": _binding()}, clock=lambda: 150.0
    )
    monkeypatch.setattr(
        client, "_account_clients", {"account-a": _FakeAccountClient(state=_FakeState())}
    )
    configure_service_read(client)
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
    configure_service_read(client)
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
    configure_service_read(client)
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-a")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "SCOPE_DENIED"


def test_unregistered_account_is_not_found():
    configure_service_read(AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={}))
    app = _app()

    response = _get(app, "/api/v1/service-read/accounts/account-z")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "ACCOUNT_NOT_CONFIGURED"


def test_transport_failure_is_reported_as_unavailable(monkeypatch):
    client = AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={"account-a": _binding()})
    monkeypatch.setattr(
        client,
        "_account_clients",
        {"account-a": _FakeAccountClient(error=_StubError("BUSINESS_OUTCOME_UNKNOWN"))},
    )
    configure_service_read(client)
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
    configure_service_read(client)
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
    configure_service_read(client)
    app = _app()

    response = _get(app, "/api/v1/service-read/strategy-health/scope-a")

    assert response.status_code == 200
    assert response.json()["quality"] == "not_collected"
    assert response.json()["is_healthy"] is False


def test_consumer_registry_endpoint_lists_recorded_evidence():
    configure_service_read(AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={}))
    app = _app()

    response = _get(app, "/api/v1/service-read/consumers")

    assert response.status_code == 200
    payload = response.json()
    ids = {item["consumer_id"] for item in payload["consumers"]}
    assert "manual-and-ai-orders" in ids
    assert payload["migrated"] == ["order-status", "strategy-health"]


def test_health_view_without_a_bound_scope_is_refused():
    configure_service_read(AuthorizedServiceReadClient(_FakeRuntime(), account_bindings={}))
    app = _app()

    response = _get(app, "/api/v1/service-read/strategy-health/scope-z")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SCOPE_NOT_CONFIGURED"


def test_neutral_views_keep_the_read_quality_enum():
    view = StrategyHealthView.not_collected("strategy-a", "scope-a")

    assert view.quality is ReadQuality.NOT_COLLECTED
    assert view.is_healthy is False
