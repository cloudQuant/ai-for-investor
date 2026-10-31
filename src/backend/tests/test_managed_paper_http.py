"""HTTP contract tests for the managed-paper cutover and order routes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest


class _ManagedPaperRouteAdapter:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, Any, str]] = []
        self.queries: list[tuple[str, str, str]] = []
        self.cutovers: list[tuple[str, str]] = []

    async def submit_manual(
        self, *, subject: str, request: Any, idempotency_key: str
    ) -> dict[str, Any]:
        self.submissions.append((subject, request, idempotency_key))
        return {
            "intent_id": "afi-manual-" + "a" * 64,
            "state": "ACKED",
            "status": "executing",
            "source": "managed_paper",
        }

    async def read_order(
        self, *, subject: str, legacy_account_id: str, intent_id: str
    ) -> dict[str, Any]:
        self.queries.append((subject, legacy_account_id, intent_id))
        return {
            "intent_id": intent_id,
            "state": "ACKED",
            "status": "executing",
            "source": "managed_paper",
        }

    async def prepare_cutover(
        self, *, subject: str, legacy_account_id: str
    ) -> dict[str, Any]:
        self.cutovers.append((subject, legacy_account_id))
        return {
            "receipt_id": "receipt-1",
            "account_id": legacy_account_id,
            "state": "ACTIVE",
            "data_migrated": False,
            "legacy_ledger_retained_read_only": True,
            "source": "managed_paper",
        }


@pytest.mark.asyncio
async def test_manual_http_submit_and_status_url_use_managed_journal(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    from app import main
    from app.api.paper_trading import get_managed_paper_order_adapter

    adapter = _ManagedPaperRouteAdapter()
    main.app.dependency_overrides[get_managed_paper_order_adapter] = lambda: adapter
    try:
        submitted = await client.post(
            "/api/v1/paper-trading/orders",
            headers={**auth_headers, "Idempotency-Key": "manual-click-42"},
            json={
                "account_id": "legacy-account-1",
                "symbol": "BTCUSDT",
                "order_type": "market",
                "side": "buy",
                "size": 0.25,
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.headers["X-Paper-Data-Source"] == "managed_paper"
        payload = submitted.json()
        assert payload["state"] == "ACKED"
        status_url = urlparse(payload["status_url"])
        assert status_url.path.endswith(
            f"/managed-orders/{payload['intent_id']}"
        )
        assert parse_qs(status_url.query) == {"account_id": ["legacy-account-1"]}
        assert adapter.submissions[0][2] == "manual-click-42"

        status_response = await client.get(
            f"{status_url.path}?{status_url.query}", headers=auth_headers
        )
        assert status_response.status_code == 200, status_response.text
        assert status_response.headers["X-Paper-Data-Source"] == "managed_paper"
        assert status_response.json()["intent_id"] == payload["intent_id"]
        assert adapter.queries == [
            (adapter.submissions[0][0], "legacy-account-1", payload["intent_id"])
        ]
    finally:
        main.app.dependency_overrides.pop(get_managed_paper_order_adapter, None)


@pytest.mark.asyncio
async def test_manual_http_requires_an_explicit_idempotency_key(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/paper-trading/orders",
        headers=auth_headers,
        json={
            "account_id": "legacy-account-1",
            "symbol": "BTCUSDT",
            "order_type": "market",
            "side": "buy",
            "size": 1,
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_cutover_requires_confirmation_and_returns_receipt(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    from app import main
    from app.api.paper_trading import get_managed_paper_order_adapter

    adapter = _ManagedPaperRouteAdapter()
    main.app.dependency_overrides[get_managed_paper_order_adapter] = lambda: adapter
    try:
        refused = await client.post(
            "/api/v1/paper-trading/accounts/legacy-account-1/managed-cutover",
            headers=auth_headers,
            json={"confirmed": False},
        )
        assert refused.status_code == 422
        assert adapter.cutovers == []

        accepted = await client.post(
            "/api/v1/paper-trading/accounts/legacy-account-1/managed-cutover",
            headers=auth_headers,
            json={"confirmed": True},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.headers["X-Paper-Data-Source"] == "managed_paper"
        assert accepted.json()["data_migrated"] is False
        assert accepted.json()["legacy_ledger_retained_read_only"] is True
        assert len(adapter.cutovers) == 1
        assert adapter.cutovers[0][0]
        assert adapter.cutovers[0][1] == "legacy-account-1"
    finally:
        main.app.dependency_overrides.pop(get_managed_paper_order_adapter, None)


@pytest.mark.asyncio
async def test_legacy_order_list_is_explicitly_source_separated(
    client: Any,
    auth_headers: dict[str, str],
) -> None:
    from app import main
    from app.api.paper_trading import get_paper_trading_service

    service = SimpleNamespace(list_orders=AsyncMock(return_value=([], 0)))
    main.app.dependency_overrides[get_paper_trading_service] = lambda: service
    try:
        response = await client.get("/api/v1/paper-trading/orders", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.headers["X-Paper-Data-Source"] == "legacy"
        assert response.json() == {"total": 0, "items": []}
    finally:
        main.app.dependency_overrides.pop(get_paper_trading_service, None)
