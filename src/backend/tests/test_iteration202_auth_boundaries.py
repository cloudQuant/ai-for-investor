from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import get_settings
from app.main import app
from app.services import param_optimization_service as optimization_service
from app.utils.security import create_access_token, create_refresh_token


def _signed_token(
    token_type: str | None,
    *,
    subject: str = "iteration202-user",
    expires_at: datetime | None = None,
) -> str:
    """Create a local JWT for exercising resource-authentication boundaries."""
    settings = get_settings()
    payload: dict[str, str | datetime] = {
        "sub": subject,
        "username": subject,
        "exp": expires_at or datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    if token_type is not None:
        payload["token_type"] = token_type
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/test",
            "headers": [],
            "query_string": b"",
        }
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _disable_app_lifespan(monkeypatch) -> None:
    import app.main as main_module

    monkeypatch.setattr(main_module, "run_startup", AsyncMock())
    monkeypatch.setattr(main_module, "run_shutdown", AsyncMock())


@pytest.mark.parametrize(
    "token_kind",
    ["refresh", "missing-purpose", "unknown-purpose", "expired-access"],
)
async def test_required_http_route_rejects_non_access_tokens(
    client, monkeypatch, token_kind: str
) -> None:
    import app.api.optimization_api as optimization_api

    if token_kind == "refresh":
        token = create_refresh_token({"sub": "user-b", "username": "user-b"})
    elif token_kind == "missing-purpose":
        token = _signed_token(None, subject="user-b")
    elif token_kind == "unknown-purpose":
        token = _signed_token("service", subject="user-b")
    else:
        token = _signed_token(
            "access",
            subject="user-b",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    downstream = Mock(return_value={"status": "running"})
    monkeypatch.setattr(optimization_api, "get_optimization_progress", downstream)

    response = await client.get(
        "/api/v1/optimization/progress/iteration202-auth-route",
        headers=_auth_headers(token),
    )

    assert response.status_code == 401
    assert downstream.call_count == 0


async def test_optional_auth_does_not_accept_refresh_or_missing_purpose() -> None:
    from app.api._dependencies import get_current_user_optional

    for token in (
        create_refresh_token({"sub": "user-b", "username": "user-b"}),
        _signed_token(None, subject="user-b"),
    ):
        request = _request()
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        current_user = await get_current_user_optional(request=request, credentials=credentials)

        assert current_user is None
        assert not hasattr(request.state, "user_id")


@pytest.mark.parametrize("token_kind", ["refresh", "missing-purpose", "unknown-purpose"])
def test_backtest_websocket_rejects_non_access_tokens_before_business_lookup(
    monkeypatch, token_kind: str
) -> None:
    import app.api.backtest_enhanced as backtest_api

    _disable_app_lifespan(monkeypatch)

    if token_kind == "refresh":
        token = create_refresh_token({"sub": "user-b", "username": "user-b"})
    elif token_kind == "missing-purpose":
        token = _signed_token(None, subject="user-b")
    else:
        token = _signed_token("service", subject="user-b")

    get_service = Mock(side_effect=AssertionError("business lookup must not run"))
    monkeypatch.setattr(backtest_api, "get_backtest_service", get_service)

    with TestClient(app) as test_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with test_client.websocket_connect(
                "/ws/backtest/iteration202-auth-route",
                subprotocols=["access-token", token],
            ):
                pass

    assert exc_info.value.code == 1008
    get_service.assert_not_called()


def test_backtest_websocket_accepts_access_token(monkeypatch) -> None:
    import app.api.backtest_enhanced as backtest_api

    _disable_app_lifespan(monkeypatch)

    subject = "iteration202-ws-owner"
    service = SimpleNamespace(
        get_task_status=AsyncMock(return_value=SimpleNamespace(value="completed")),
        get_result=AsyncMock(return_value=None),
    )
    get_service = Mock(return_value=service)
    monkeypatch.setattr(backtest_api, "get_backtest_service", get_service)
    token = create_access_token({"sub": subject, "username": subject})

    with TestClient(app) as test_client:
        with test_client.websocket_connect(
            "/ws/backtest/iteration202-access-ws",
            subprotocols=["access-token", token],
        ) as websocket:
            assert websocket.receive_json()["type"] == "connected"

    get_service.assert_called_once_with()
    service.get_task_status.assert_awaited_once_with("iteration202-access-ws", user_id=subject)


async def test_access_token_reaches_required_route_and_refresh_rotation_remains_available(
    client, monkeypatch
) -> None:
    import app.api.optimization_api as optimization_api

    username = f"iteration202_{uuid4().hex[:10]}"
    registration = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "Iteration202Pass123!",
        },
    )
    assert registration.status_code == 200
    registered_user = registration.json()

    login = await client.post(
        "/api/v1/auth/login/refresh",
        json={"username": username, "password": "Iteration202Pass123!"},
    )
    assert login.status_code == 200
    original = login.json()

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert rotated.status_code == 200
    rotated_tokens = rotated.json()
    assert rotated_tokens["refresh_token"] != original["refresh_token"]

    downstream = Mock(
        side_effect=lambda task_id, user_id: {
            "task_id": task_id,
            "status": "running",
            "user_id": user_id,
        }
    )
    monkeypatch.setattr(optimization_api, "get_optimization_progress", downstream)

    access_response = await client.get(
        "/api/v1/optimization/progress/iteration202-access-route",
        headers=_auth_headers(rotated_tokens["access_token"]),
    )
    assert access_response.status_code == 200
    assert access_response.json()["user_id"] == registered_user["id"]
    downstream.assert_called_once_with("iteration202-access-route", user_id=registered_user["id"])

    revoked_refresh_response = await client.get(
        "/api/v1/optimization/progress/iteration202-revoked-refresh",
        headers=_auth_headers(original["refresh_token"]),
    )
    assert revoked_refresh_response.status_code == 401
    assert downstream.call_count == 1

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
    )
    assert replay.status_code == 401


def _runtime_task(task_id: str) -> None:
    optimization_service._set_task(
        task_id,
        {
            "status": "running",
            "strategy_id": "foreign-strategy-secret",
            "param_names": ["period"],
            "param_ranges": {"period": {"start": 1, "end": 2, "step": 1}},
            "total": 2,
            "completed": 1,
            "failed": 0,
            "results": [{"params": {"period": 1}, "metrics": {"annual_return": 99.0}}],
            "n_workers": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


async def test_optimization_routes_fail_closed_on_user_scoped_database_errors(
    client, monkeypatch
) -> None:
    task_id = f"iteration202-{uuid4().hex}"
    _runtime_task(task_id)

    manager = Mock()
    manager.get_task.return_value = None
    manager.set_cancelled.return_value = False
    monkeypatch.setattr(
        optimization_service,
        "get_optimization_execution_manager",
        lambda: manager,
    )

    def database_unavailable(_operation):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(optimization_service, "_run_async", database_unavailable)
    headers = _auth_headers(create_access_token({"sub": "user-b", "username": "user-b"}))

    progress = await client.get(f"/api/v1/optimization/progress/{task_id}", headers=headers)
    results = await client.get(f"/api/v1/optimization/results/{task_id}", headers=headers)
    cancellation = await client.post(f"/api/v1/optimization/cancel/{task_id}", headers=headers)

    assert progress.status_code == 404
    assert results.status_code == 404
    assert cancellation.status_code == 404
    for response in (progress, results, cancellation):
        assert "foreign-strategy-secret" not in response.text
        assert "99.0" not in response.text

    task_after = optimization_service._get_task(task_id)
    assert task_after is not None
    assert task_after["status"] == "running"
    assert task_after["results"][0]["metrics"]["annual_return"] == 99.0
    assert all(call.kwargs["user_id"] == "user-b" for call in manager.get_task.call_args_list)
    manager.set_cancelled.assert_called_once_with(task_id, "user-b")


async def test_optimization_routes_preserve_owner_access_and_reject_foreign_owner(
    client, monkeypatch
) -> None:
    task_id = f"iteration202-owner-{uuid4().hex}"
    _runtime_task(task_id)
    database_task = SimpleNamespace(
        status="running",
        strategy_id="foreign-strategy-secret",
        param_ranges={"period": {"start": 1, "end": 2, "step": 1}},
        total=2,
        completed=1,
        failed=0,
        results=[{"params": {"period": 1}, "metrics": {"annual_return": 99.0}}],
        n_workers=1,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        error_message=None,
    )
    manager = Mock()
    manager.get_task.side_effect = lambda _task_id, user_id=None: (
        database_task if user_id == "owner-a" else None
    )
    manager.set_cancelled.side_effect = lambda _task_id, user_id=None: user_id == "owner-a"
    monkeypatch.setattr(
        optimization_service,
        "get_optimization_execution_manager",
        lambda: manager,
    )
    monkeypatch.setattr(optimization_service, "_run_async", lambda result: result)

    owner_headers = _auth_headers(create_access_token({"sub": "owner-a", "username": "owner-a"}))
    foreign_headers = _auth_headers(create_access_token({"sub": "user-b", "username": "user-b"}))

    owner_progress = await client.get(
        f"/api/v1/optimization/progress/{task_id}", headers=owner_headers
    )
    owner_results = await client.get(
        f"/api/v1/optimization/results/{task_id}", headers=owner_headers
    )
    foreign_progress = await client.get(
        f"/api/v1/optimization/progress/{task_id}", headers=foreign_headers
    )
    foreign_results = await client.get(
        f"/api/v1/optimization/results/{task_id}", headers=foreign_headers
    )
    foreign_cancel = await client.post(
        f"/api/v1/optimization/cancel/{task_id}", headers=foreign_headers
    )
    owner_cancel = await client.post(
        f"/api/v1/optimization/cancel/{task_id}", headers=owner_headers
    )

    assert owner_progress.status_code == 200
    assert owner_results.status_code == 200
    assert owner_results.json()["rows"][0]["annual_return"] == 99.0
    assert foreign_progress.status_code == 404
    assert foreign_results.status_code == 404
    assert foreign_cancel.status_code == 404
    assert owner_cancel.status_code == 200
    assert optimization_service._get_task(task_id)["status"] == "cancelled"
