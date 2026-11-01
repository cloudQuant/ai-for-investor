"""Integration tests for the paper-trading account and managed-order boundary.

Exercises the real service + persistence layer (no service mocks) against the
DB configured for the test session — on CI this is the Postgres service
container, locally it is the sqlite/Postgres test DB from conftest.

The legacy paper ledger remains a read-only projection: new orders are
accepted only through the managed-paper owner (service-read binding plus a
cutover receipt).  In a plain deployment without that owner the submit
boundary must fail closed and leave the legacy ledger untouched.

Backlog: REFACTORING_BACKLOG.md P2#9 (integration coverage for paper/live flow).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

_BASE = "/api/v1/paper-trading"
_SYMBOL = "000001.SZ"  # _get_simulated_price returns a deterministic 10.5 for 000001


class TestPaperTradingRoundTrip:
    """End-to-end paper-trading lifecycle against the real service layer."""

    async def test_full_paper_trading_lifecycle(self, client: AsyncClient, auth_headers: dict):
        # Step 1: create a paper-trading account
        create_resp = await client.post(
            f"{_BASE}/accounts",
            json={
                "name": "Integration Account",
                "initial_cash": 100000.0,
                "commission_rate": 0.001,
                "slippage_rate": 0.001,
            },
            headers=auth_headers,
        )
        assert create_resp.status_code == 200, create_resp.text
        account = create_resp.json()
        account_id = account["id"]
        assert account["current_cash"] == pytest.approx(100000.0)
        assert account["initial_cash"] == pytest.approx(100000.0)

        # Step 2: the fresh account projects empty read-only ledger views.
        for path in ("positions", "trades", "orders"):
            view_resp = await client.get(
                f"{_BASE}/{path}",
                params={"account_id": account_id},
                headers=auth_headers,
            )
            assert view_resp.status_code == 200, view_resp.text
            assert view_resp.json()["items"] == []
            assert view_resp.headers["X-Paper-Data-Source"] == "legacy"

        # Step 3: the account itself round-trips through the legacy selector.
        acct_resp = await client.get(
            f"{_BASE}/accounts/{account_id}",
            headers=auth_headers,
        )
        assert acct_resp.status_code == 200, acct_resp.text
        assert acct_resp.json()["current_cash"] == pytest.approx(100000.0)

        # Step 4: clean up — the account is soft-deleted and no longer active.
        del_resp = await client.delete(
            f"{_BASE}/accounts/{account_id}",
            headers=auth_headers,
        )
        assert del_resp.status_code in (200, 204), del_resp.text
        deleted_resp = await client.get(
            f"{_BASE}/accounts/{account_id}",
            headers=auth_headers,
        )
        assert deleted_resp.status_code == 200, deleted_resp.text
        assert deleted_resp.json()["is_active"] is False

    async def test_order_rejected_without_configured_managed_owner(
        self, client: AsyncClient, auth_headers: dict
    ):
        """A submit outside the managed owner fails closed, not via legacy matching."""
        create_resp = await client.post(
            f"{_BASE}/accounts",
            json={"name": "Tiny Account", "initial_cash": 100.0},
            headers=auth_headers,
        )
        assert create_resp.status_code == 200, create_resp.text
        account_id = create_resp.json()["id"]

        resp = await client.post(
            f"{_BASE}/orders",
            json={
                "account_id": account_id,
                "symbol": _SYMBOL,
                "order_type": "market",
                "side": "buy",
                "size": 100000,
            },
            headers={**auth_headers, "Idempotency-Key": "paper-flow-unbound-owner"},
        )
        assert resp.status_code == 503, resp.text
        assert resp.json()["details"]["code"] == "SERVICE_READ_NOT_CONFIGURED"

        # No fallback to the retired legacy matcher: cash, positions, and
        # trades stay exactly as they were.
        acct = await client.get(f"{_BASE}/accounts/{account_id}", headers=auth_headers)
        assert acct.json()["current_cash"] == pytest.approx(100.0)
        for path in ("positions", "trades", "orders"):
            view_resp = await client.get(
                f"{_BASE}/{path}",
                params={"account_id": account_id},
                headers=auth_headers,
            )
            assert view_resp.status_code == 200, view_resp.text
            assert view_resp.json()["items"] == []

        await client.delete(f"{_BASE}/accounts/{account_id}", headers=auth_headers)
