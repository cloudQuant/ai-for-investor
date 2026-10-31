"""Focused local test for the authenticated, read-only Gateway health socket."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI


async def _drive_asgi_websocket(
    app: FastAPI,
    *,
    path: str,
    token_subject: str,
    messages: tuple[str, ...],
    on_receive_text: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Drive one ASGI WebSocket scope without the incompatible TestClient pair."""

    incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    outgoing: list[dict[str, Any]] = []
    await incoming.put({"type": "websocket.connect"})
    for message in messages:
        await incoming.put({"type": "websocket.receive", "text": message})

    async def receive() -> dict[str, Any]:
        event = await incoming.get()
        if event["type"] == "websocket.receive" and on_receive_text is not None:
            on_receive_text(event["text"])
        return event

    async def send(event: dict[str, Any]) -> None:
        outgoing.append(event)

    subprotocols = ["access-token", token_subject]
    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"afi09.synthetic.test"),
            (b"sec-websocket-protocol", ", ".join(subprotocols).encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 80),
        "subprotocols": subprotocols,
        "state": {},
        "extensions": {},
    }
    await app(scope, receive, send)
    return outgoing


def test_afi09_gateway_health_ws_is_an_authorized_projection_only() -> None:
    import app.api._dependencies as auth_dependencies
    from app.api.service_gateway_ws import router as gateway_health_ws_router
    from app.api.service_read import configure_service_read
    from app.db.database import get_db
    from app.models.user import User
    from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
    from app.services.service_read.contracts import AccountReadView, ReadQuality
    from app.services.service_read.gateway_health import GatewayHealthView

    account_ref = "gateway-health-ws-account"
    owner_subject = "gateway-health-ws-owner"
    account = AccountReadView(
        account_ref=account_ref,
        execution_domain_ref="gateway-health-ws-domain",
        currency="USD",
        quality=ReadQuality.FRESH,
        session_generation="owner-generation-7",
        cursor=14,
        observed_at_utc="2026-10-16T00:00:00Z",
        received_age_seconds=0.2,
        fresh_for_seconds=10.0,
    )
    health = GatewayHealthView.from_replies(
        account_ref,
        {
            "latest_cursor": 14,
            "state_status": {
                "session_generation": "owner-generation-7",
                "ready": True,
                "fresh_for_seconds": 10.0,
            },
        },
        account,
    )

    class Worker:
        reads = 0

        async def read_account(self, _account_ref: str, *, currency: str | None = None) -> Any:
            return account

        async def read_order(self, _scope_ref: str, _intent_id: str) -> Any:
            return None

        async def read_strategy_health(self, _scope_ref: str) -> Any:
            return None

        async def read_gateway_health(self, requested_ref: str) -> Any:
            assert requested_ref == account_ref
            self.reads += 1
            return health

    worker = Worker()
    configure_service_read(
        ServiceReadAccessDirectory(
            {owner_subject: ReadAccess(worker, allow_account_refs=frozenset({account_ref}))}
        )
    )

    class Database:
        rollback_calls = 0

        async def rollback(self) -> None:
            self.rollback_calls += 1

        async def get(self, model: type[Any], subject: str) -> Any:
            assert model is User
            return SimpleNamespace(id=subject, is_active=True, principal_kind="HUMAN")

    db = Database()

    async def database_dependency():
        yield db

    app = FastAPI()
    app.include_router(gateway_health_ws_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = database_dependency
    original_decoder = auth_dependencies.decode_access_token
    auth_dependencies.decode_access_token = lambda token: {
        "sub": token,
        "username": "synthetic-user",
    }
    try:
        async def exercise_asgi() -> None:
            path = f"/api/v1/service-gateway/ws/accounts/{account_ref}/health"
            events = await _drive_asgi_websocket(
                app,
                path=path,
                token_subject=owner_subject,
                messages=("refresh", "close"),
            )
            accepts = [event for event in events if event["type"] == "websocket.accept"]
            projections = [event for event in events if event["type"] == "websocket.send"]
            assert len(accepts) == 1
            assert accepts[0].get("subprotocol") == "access-token"
            assert len(projections) == 2
            first = json.loads(projections[0]["text"])
            second = json.loads(projections[1]["text"])
            assert first == second
            assert first["type"] == "gateway_health"
            assert first["data"]["gateway_session"]["session_generation"] == (
                "owner-generation-7"
            )
            assert first["data"]["account_observation"]["same_session_generation"] is True
            assert first["data"]["market_data_feed"]["status"] == "unobserved"
            assert "credential" not in str(first).lower()

            denied_events = await _drive_asgi_websocket(
                app,
                path=path,
                token_subject="another-owner",
                messages=(),
            )
            denied_closes = [
                event
                for event in denied_events
                if event.get("type") == "websocket.close"
            ]
            assert len(denied_closes) == 1
            assert denied_closes[0].get("code") == 1008

        asyncio.run(exercise_asgi())
        assert worker.reads == 2
    finally:
        auth_dependencies.decode_access_token = original_decoder
        configure_service_read(None)


def _assert_gateway_health_ws_rejects_post_frame_authorization_loss(
    failure: str,
) -> None:
    import app.api._dependencies as auth_dependencies
    from app.api.service_gateway_ws import router as gateway_health_ws_router
    from app.api.service_read import configure_service_read
    from app.db.database import get_db
    from app.models.user import User
    from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
    from app.services.service_read.contracts import AccountReadView, ReadQuality
    from app.services.service_read.gateway_health import GatewayHealthView

    assert failure in {"expired", "revoked"}
    account_ref = f"gateway-health-ws-{failure}-account"
    owner_subject = f"gateway-health-ws-{failure}-owner"
    expiry = 1_800_000_000
    clock = {"now": expiry - 1}
    decoder_calls = 0

    account = AccountReadView(
        account_ref=account_ref,
        execution_domain_ref=f"{account_ref}-domain",
        currency="USD",
        quality=ReadQuality.FRESH,
        session_generation="owner-generation-9",
        cursor=21,
        observed_at_utc="2026-10-17T00:00:00Z",
        received_age_seconds=0.1,
        fresh_for_seconds=10.0,
    )
    health = GatewayHealthView.from_replies(
        account_ref,
        {
            "latest_cursor": 21,
            "state_status": {
                "session_generation": "owner-generation-9",
                "ready": True,
                "fresh_for_seconds": 10.0,
            },
        },
        account,
    )

    class Database:
        def __init__(self) -> None:
            self.owner_active = True
            self.cached_owner: Any | None = None
            self.rollback_calls = 0
            self.get_calls = 0

        async def rollback(self) -> None:
            # Match AsyncSession.rollback(): end the old read transaction and
            # expire its identity map before checking persisted ownership again.
            self.rollback_calls += 1
            self.cached_owner = None

        async def get(self, model: type[Any], subject: str) -> Any:
            assert model is User
            assert subject == owner_subject
            self.get_calls += 1
            if self.cached_owner is None:
                self.cached_owner = SimpleNamespace(
                    id=subject,
                    is_active=self.owner_active,
                    principal_kind="HUMAN",
                )
            return self.cached_owner

    db = Database()

    class Worker:
        def __init__(self) -> None:
            self.reads = 0

        async def read_account(self, _account_ref: str, *, currency: str | None = None) -> Any:
            return account

        async def read_order(self, _scope_ref: str, _intent_id: str) -> Any:
            return None

        async def read_strategy_health(self, _scope_ref: str) -> Any:
            return None

        async def read_gateway_health(self, requested_ref: str) -> Any:
            assert requested_ref == account_ref
            self.reads += 1
            if failure == "revoked":
                # Simulate owner deactivation after the first projection. The
                # next check must not reuse the AsyncSession's cached User.
                db.owner_active = False
            return health

    worker = Worker()
    configure_service_read(
        ServiceReadAccessDirectory(
            {owner_subject: ReadAccess(worker, allow_account_refs=frozenset({account_ref}))}
        )
    )
    app = FastAPI()
    app.include_router(gateway_health_ws_router, prefix="/api/v1")

    async def database_dependency():
        yield db

    app.dependency_overrides[get_db] = database_dependency

    def controlled_decoder(token: str) -> dict[str, Any] | None:
        nonlocal decoder_calls
        decoder_calls += 1
        assert token == owner_subject
        if failure == "expired" and clock["now"] >= expiry:
            return None
        return {
            "sub": owner_subject,
            "username": "synthetic-user",
            "exp": expiry,
            "token_type": "access",
        }

    original_decoder = auth_dependencies.decode_access_token
    auth_dependencies.decode_access_token = controlled_decoder
    try:
        async def exercise_asgi() -> list[dict[str, Any]]:
            path = f"/api/v1/service-gateway/ws/accounts/{account_ref}/health"

            def after_message(message: str) -> None:
                if failure == "expired" and message == "refresh":
                    # The token is valid for the handshake and first frame,
                    # then expires before the client's next refresh.
                    clock["now"] = expiry

            return await _drive_asgi_websocket(
                app,
                path=path,
                token_subject=owner_subject,
                messages=("refresh", "close"),
                on_receive_text=after_message,
            )

        events = asyncio.run(exercise_asgi())
        accepts = [event for event in events if event["type"] == "websocket.accept"]
        projections = [event for event in events if event["type"] == "websocket.send"]
        closes = [event for event in events if event.get("type") == "websocket.close"]
        assert len(accepts) == 1
        assert accepts[0].get("subprotocol") == "access-token"
        assert len(projections) == 1
        assert len(closes) == 1
        assert closes[0].get("code") == 1008
        assert worker.reads == 1
        assert decoder_calls == 3  # handshake, first projection, rejected refresh
        assert db.get_calls == (2 if failure == "expired" else 3)
        assert db.rollback_calls == db.get_calls
    finally:
        auth_dependencies.decode_access_token = original_decoder
        configure_service_read(None)


def test_afi09_gateway_health_ws_revalidates_expiry_before_next_worker_read() -> None:
    _assert_gateway_health_ws_rejects_post_frame_authorization_loss("expired")


def test_afi09_gateway_health_ws_rechecks_owner_after_fresh_read_transaction() -> None:
    _assert_gateway_health_ws_rejects_post_frame_authorization_loss("revoked")

