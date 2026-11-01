"""Focused HTTP checks for AFI's persisted personal-owner boundary."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.api.service_read import configure_service_read
from app.db import database
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.models.user import User
from app.models.workspace import Workspace
from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
from app.services.service_read.contracts import AccountReadView
from app.utils.security import create_access_token


class _ObservedReadWorker:
    """Local service caller that records only the approved request coordinates."""

    def __init__(self) -> None:
        self.account_calls: list[tuple[str, str | None]] = []
        self.order_calls: list[tuple[str, str]] = []
        self.health_calls: list[str] = []

    async def read_account(
        self, account_ref: str, *, currency: str | None = None
    ) -> AccountReadView:
        self.account_calls.append((account_ref, currency))
        return AccountReadView.unavailable(
            account_ref,
            execution_domain_ref="synthetic:afi01-owner-test",
            currency=currency or "USD",
            detail_code="SYNTHETIC_NO_PROVIDER",
        )

    async def read_order(self, scope_ref: str, intent_id: str) -> Any:
        self.order_calls.append((scope_ref, intent_id))
        raise AssertionError("the owner-scope test must not query an order")

    async def read_strategy_health(self, scope_ref: str) -> Any:
        self.health_calls.append(scope_ref)
        raise AssertionError("the owner-scope test must not query strategy health")


def _token(subject: str, username: str) -> str:
    return create_access_token(
        {"sub": subject, "username": username}, expires_delta=timedelta(minutes=5)
    )


@pytest.mark.asyncio
async def test_service_and_persisted_resources_use_exact_active_owner_scope(
    client: AsyncClient,
) -> None:
    owner_a_id = "afi01-owner-a"
    owner_b_id = "afi01-owner-b"
    inactive_id = "afi01-inactive-owner"
    service_id = "afi01-service-principal"
    missing_id = "afi01-missing-owner"

    owner_a = User(
        id=owner_a_id,
        username="afi01-owner-a",
        email="afi01-owner-a@example.invalid",
        hashed_password="synthetic-only",
        is_active=True,
        # The existing approval migration deliberately leaves legacy users
        # UNKNOWN. That remains an owner identity only; it is not HUMAN proof.
        principal_kind="UNKNOWN",
    )
    owner_b = User(
        id=owner_b_id,
        username="afi01-owner-b",
        email="afi01-owner-b@example.invalid",
        hashed_password="synthetic-only",
        is_active=True,
        principal_kind="HUMAN",
    )
    inactive = User(
        id=inactive_id,
        username="afi01-inactive-owner",
        email="afi01-inactive-owner@example.invalid",
        hashed_password="synthetic-only",
        is_active=False,
        principal_kind="HUMAN",
    )
    service_principal = User(
        id=service_id,
        username="afi01-service-principal",
        email="afi01-service-principal@example.invalid",
        hashed_password="synthetic-only",
        is_active=True,
        principal_kind="SERVICE",
    )

    async with database.async_session_maker() as db:
        db.add_all([owner_a, owner_b, inactive, service_principal])
        await db.flush()
        workspace = Workspace(
            id="afi01-workspace-a",
            user_id=owner_a_id,
            name="owner-a-workspace",
            workspace_type="research",
        )
        portfolio = PortfolioCompositionVersion(
            id="afi01-portfolio-version-a",
            owner_subject=owner_a_id,
            portfolio_ref="portfolio-a",
            membership_version=1,
            source_type="manual",
            base_currency="USD",
            members=[],
            membership_sha256="a" * 64,
        )
        db.add_all([workspace, portfolio])
        await db.commit()

    workers = {
        "owner_a": _ObservedReadWorker(),
        "owner_b": _ObservedReadWorker(),
        "inactive": _ObservedReadWorker(),
        "service": _ObservedReadWorker(),
        "missing": _ObservedReadWorker(),
    }
    configure_service_read(
        ServiceReadAccessDirectory(
            {
                owner_a_id: ReadAccess(
                    worker=workers["owner_a"],
                    allow_account_refs=frozenset({"account-a"}),
                    allow_monitor_scope_refs=frozenset({"strategy-a"}),
                ),
                owner_b_id: ReadAccess(
                    worker=workers["owner_b"],
                    allow_account_refs=frozenset({"account-b"}),
                ),
                inactive_id: ReadAccess(
                    worker=workers["inactive"],
                    allow_account_refs=frozenset({"account-inactive"}),
                ),
                service_id: ReadAccess(
                    worker=workers["service"],
                    allow_account_refs=frozenset({"account-service"}),
                ),
                missing_id: ReadAccess(
                    worker=workers["missing"],
                    allow_account_refs=frozenset({"account-missing"}),
                ),
            }
        )
    )

    token_a = _token(owner_a_id, owner_a.username)
    token_b = _token(owner_b_id, owner_b.username)
    token_inactive = _token(inactive_id, inactive.username)
    token_service = _token(service_id, service_principal.username)
    token_missing = _token(missing_id, "afi01-missing-owner")

    try:
        # Client tenant/workspace headers do not override the persisted JWT
        # owner or the deployment's exact subject-to-service binding.
        response = await client.get(
            "/api/v1/service-read/accounts/account-a?currency=USD",
            headers={
                "Authorization": f"Bearer {token_a}",
                "X-Tenant-Ref": owner_b_id,
                "X-Workspace-Id": "afi01-workspace-b",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["account_ref"] == "account-a"
        assert response.json()["quality"] == "unavailable"
        assert workers["owner_a"].account_calls == [("account-a", "USD")]

        own_account_b = await client.get(
            "/api/v1/service-read/accounts/account-b",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert own_account_b.status_code == 200, own_account_b.text
        assert own_account_b.json()["quality"] == "unavailable"
        assert workers["owner_b"].account_calls == [("account-b", None)]

        # A valid second owner cannot use A's configured account or strategy
        # selector, even when the client supplies A's workspace header.
        cross_account = await client.get(
            "/api/v1/service-read/accounts/account-a",
            headers={
                "Authorization": f"Bearer {token_b}",
                "X-Workspace-Id": "afi01-workspace-a",
            },
        )
        cross_strategy = await client.get(
            "/api/v1/service-read/strategy-health/strategy-a",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert cross_account.status_code == 403
        assert cross_strategy.status_code == 403
        assert workers["owner_a"].account_calls == [("account-a", "USD")]
        assert workers["owner_b"].account_calls == [("account-b", None)]
        assert workers["owner_b"].health_calls == []

        # A server-directory entry alone is not an owner grant: it must join to
        # an active persisted user. Explicit service identities and inactive
        # owners are denied before their worker can be called.
        for token, selector in (
            (token_missing, "account-missing"),
            (token_inactive, "account-inactive"),
            (token_service, "account-service"),
        ):
            denied = await client.get(
                f"/api/v1/service-read/accounts/{selector}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert denied.status_code == 403, denied.text
        assert workers["inactive"].account_calls == []
        assert workers["service"].account_calls == []
        assert workers["missing"].account_calls == []

        # Legacy UNKNOWN remains owner-scoped but cannot publish or act as a
        # human approval principal; UNKNOWN is not upgraded by a request claim.
        approval = await client.post(
            "/api/v1/service-orders/approved-targets/policies/legacy-policy",
            json={"policy": {}},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert approval.status_code == 403
        assert approval.json()["details"]["code"] == "PERSISTED_HUMAN_PRINCIPAL_REQUIRED"
        forged_approver = await client.post(
            "/api/v1/service-orders/approved-targets",
            json={
                "scope_ref": "strategy-a",
                "strategy_version": 1,
                "instrument": "BTC/USD",
                "metadata_version": "metadata-v1",
                "side": "BUY",
                "position_effect": "OPEN",
                "order_type": "MARKET",
                "quantity": "1",
            },
            headers={
                "Authorization": f"Bearer {token_a}",
                "X-Approver-Subject": owner_b_id,
            },
        )
        assert forged_approver.status_code == 403
        assert forged_approver.json()["details"]["code"] == ("PERSISTED_HUMAN_PRINCIPAL_REQUIRED")

        # Existing persistent workspace and portfolio ownership remain the
        # boundary for those resources; the caller cannot substitute A's ID.
        workspace_a = await client.get(
            "/api/v1/workspace/afi01-workspace-a",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        workspace_b = await client.get(
            "/api/v1/workspace/afi01-workspace-a",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        portfolio_a = await client.get(
            "/api/v1/portfolio/compositions/portfolio-a/versions/1",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        portfolio_b = await client.get(
            "/api/v1/portfolio/compositions/portfolio-a/versions/1",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert workspace_a.status_code == 200, workspace_a.text
        assert workspace_b.status_code == 404
        assert portfolio_a.status_code == 200, portfolio_a.text
        assert portfolio_b.status_code == 404
    finally:
        configure_service_read(None)
