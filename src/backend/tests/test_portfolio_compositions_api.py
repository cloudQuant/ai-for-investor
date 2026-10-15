"""Deterministic HTTP projection evidence for source-separated memberships."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "synthetic-portfolio-composition-test-secret-012345")

# Settings are imported before the DB module, then dotenv loading is disabled so
# this focused API test cannot consult either repository .env file.
from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.api.portfolio import api as portfolio_api  # noqa: E402
from app.api.portfolio import router as portfolio_router  # noqa: E402
from app.api.service_read import configure_service_read  # noqa: E402
from app.db.database import get_db  # noqa: E402
from app.models.portfolio_composition import PortfolioCompositionVersion  # noqa: E402
from app.schemas.auth import TokenPayload  # noqa: E402
from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory  # noqa: E402
from app.services.service_read.contracts import AccountReadView, ReadQuality  # noqa: E402
from app.services.service_read.worker import ServiceReadWorker  # noqa: E402


class _SyntheticReadSession:
    def __init__(self, views: dict[str, AccountReadView]) -> None:
        self.views = views
        self.account_reads: list[tuple[str, str | None]] = []
        self.closed = False

    def start(self) -> None:
        pass

    def maintain(self) -> None:
        pass

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        self.account_reads.append((account_ref, currency))
        return self.views[account_ref]

    def read_order(self, scope_ref: str, intent_id: str) -> None:
        raise AssertionError("the composition projection must not read orders")

    def read_strategy_health(self, scope_ref: str) -> None:
        raise AssertionError("health is not execution attribution")

    def close(self) -> None:
        self.closed = True


def _account_view(account_ref: str, key: object, *, value: str, cash: str) -> AccountReadView:
    return AccountReadView(
        account_ref=account_ref,
        execution_domain_ref="live:synthetic-venue",
        currency="USD",
        quality=ReadQuality.FRESH,
        cash=Decimal(cash),
        value=Decimal(value),
        observed_at_utc="2026-10-15T00:00:00Z",
        account_key=key.to_dict(),
        account_key_id=key.account_key_id,
    )


def test_composition_membership_versions_and_live_overview_projection(monkeypatch):
    try:
        from bt_api_base.account_protocol import AccountKey
    except ImportError:
        pytest.skip("the service SDK account protocol is not installed")

    async def scenario() -> None:
        manager_calls = 0
        legacy_manager = object()

        def fake_get_manager() -> object:
            nonlocal manager_calls
            manager_calls += 1
            return legacy_manager

        monkeypatch.setattr(portfolio_api, "_get_manager", fake_get_manager)

        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        async def override_db():
            async with session_maker() as session:
                yield session

        owner = TokenPayload(sub="owner-a", username="owner")
        app = FastAPI()
        app.include_router(portfolio_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: owner
        app.dependency_overrides[get_db] = override_db

        first_key = AccountKey(
            provider="synthetic-provider",
            venue="synthetic-venue",
            environment="live",
            account_id="acct-1",
            subaccount_id=None,
        )
        second_key = AccountKey(
            provider="synthetic-provider",
            venue="synthetic-venue",
            environment="live",
            account_id="acct-2",
            subaccount_id="sub-1",
        )
        source_session = _SyntheticReadSession(
            {
                "account-a": _account_view("account-a", first_key, value="1000", cash="200"),
                "account-a-alias": _account_view(
                    "account-a-alias", first_key, value="1000", cash="200"
                ),
                "account-b": _account_view("account-b", second_key, value="500", cash="250"),
            }
        )
        worker = ServiceReadWorker(
            lambda: source_session,
            maintenance_interval_seconds=60,
            name="afi-composition-synthetic-read-owner",
        )
        await worker.start()
        configure_service_read(
            ServiceReadAccessDirectory(
                {
                    owner.sub: ReadAccess(
                        worker,
                        allow_account_refs={"account-a", "account-a-alias", "account-b"},
                    )
                }
            )
        )

        live_request = {
            "portfolio_ref": "primary",
            "source_type": "live",
            "base_currency": "USD",
            "members": [
                {"kind": "account", "ref": "account-a"},
                {"kind": "account", "ref": "account-a-alias"},
                {"kind": "account", "ref": "account-b"},
                {"kind": "strategy", "ref": "strategy-x"},
                {"kind": "strategy", "ref": "strategy-y"},
            ],
        }
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                created = await client.post("/api/v1/portfolio/compositions", json=live_request)
                assert created.status_code == 201, created.text
                version_one = created.json()
                assert version_one["membership_version"] == 1
                assert version_one["creditable"] is False
                assert "owner_subject" not in version_one

                forged_owner = {**live_request, "owner_subject": "owner-b"}
                rejected = await client.post("/api/v1/portfolio/compositions", json=forged_owner)
                assert rejected.status_code == 422

                unauthorized = {
                    **live_request,
                    "portfolio_ref": "not-authorized",
                    "members": [{"kind": "account", "ref": "account-outside-grant"}],
                }
                denied = await client.post("/api/v1/portfolio/compositions", json=unauthorized)
                assert denied.status_code == 403

                reversed_request = {
                    **live_request,
                    "members": list(reversed(live_request["members"])),
                }
                created_two = await client.post(
                    "/api/v1/portfolio/compositions", json=reversed_request
                )
                assert created_two.status_code == 201, created_two.text
                version_two = created_two.json()
                assert version_two["membership_version"] == 2
                assert version_two["membership_sha256"] == version_one["membership_sha256"]

                unchanged = await client.get("/api/v1/portfolio/compositions/primary/versions/1")
                assert unchanged.status_code == 200
                assert unchanged.json()["members"] == version_one["members"]

                projection = await client.get(
                    "/api/v1/portfolio/overview",
                    params={"portfolio_ref": "primary", "membership_version": 1},
                )
                assert projection.status_code == 200, projection.text
                live = projection.json()
                assert live["source_type"] == "live"
                assert live["source_status"] == "projected"
                assert live["account_total"] == {
                    "status": "current",
                    "currency": "USD",
                    "value": "1500",
                }
                assert sum(row["included_in_total"] for row in live["accounts"]) == 2
                alias_row = next(
                    row for row in live["accounts"] if row["member_ref"] == "account-a-alias"
                )
                assert alias_row["duplicate_of_ref"] == "account-a"
                assert first_key.account_id not in projection.text
                assert first_key.account_key_id not in projection.text
                assert live["strategy_attribution"] == {
                    "status": "execution_attribution_not_collected",
                    "strategy_count": 2,
                    "attributed_value": None,
                    "unattributed_account_value": "1500",
                    "residual_basis": "account total only; no strategy shares inferred",
                }
                assert [row["attributed_value"] for row in live["strategies"]] == [None, None]
                assert live["coverage"] == {
                    "complete": False,
                    "account_facts_complete": True,
                    "strategy_attribution_complete": False,
                    "code": "EXECUTION_ATTRIBUTION_NOT_COLLECTED",
                }
                assert live["creditable"] is False
                assert live["overlap_policy"] == "non_additive_display_only"
                assert "credit_amount" not in live and "budget_credit" not in live
                assert manager_calls == 0

                incomplete_selector = await client.get(
                    "/api/v1/portfolio/overview",
                    params={"portfolio_ref": "primary"},
                )
                assert incomplete_selector.status_code == 422
                assert manager_calls == 0

                overlap = await client.post(
                    "/api/v1/portfolio/compositions",
                    json={
                        "portfolio_ref": "overlap-view",
                        "source_type": "live",
                        "base_currency": "USD",
                        "members": [{"kind": "account", "ref": "account-a-alias"}],
                    },
                )
                assert overlap.status_code == 201, overlap.text
                overlap_projection = await client.get(
                    "/api/v1/portfolio/compositions/overlap-view/versions/1/projection"
                )
                assert overlap_projection.status_code == 200
                assert overlap_projection.json()["account_total"]["value"] == "1000"
                assert overlap_projection.json()["creditable"] is False

                for source_type, member in (
                    ("research", {"kind": "research_artifact", "ref": "run-1"}),
                    ("imported", {"kind": "imported_ledger", "ref": "ledger-1"}),
                    ("paper", {"kind": "paper_account", "ref": "paper-1"}),
                ):
                    source_ref = f"{source_type}-view"
                    created_source = await client.post(
                        "/api/v1/portfolio/compositions",
                        json={
                            "portfolio_ref": source_ref,
                            "source_type": source_type,
                            "base_currency": "USD",
                            "members": [member],
                        },
                    )
                    assert created_source.status_code == 201, created_source.text
                    source_projection = await client.get(
                        f"/api/v1/portfolio/compositions/{source_ref}/versions/1/projection"
                    )
                    assert source_projection.status_code == 200
                    body = source_projection.json()
                    assert body["source_type"] == source_type
                    assert body["source_status"] == "adapter_not_integrated"
                    assert body["account_total"]["value"] is None
                    assert body["coverage"]["complete"] is False

                app.dependency_overrides[get_current_user] = lambda: TokenPayload(
                    sub="owner-b", username="other"
                )
                private = await client.get(
                    "/api/v1/portfolio/compositions/primary/versions/1/projection"
                )
                assert private.status_code == 404

                async def legacy_compact_overview(_current_user, manager):
                    assert manager is legacy_manager
                    return {"legacy_overview": True}

                monkeypatch.setattr(
                    portfolio_api, "_compact_portfolio_overview", legacy_compact_overview
                )
                legacy = await client.get(
                    "/api/v1/portfolio/overview", params={"summary_only": "true"}
                )
                assert legacy.status_code == 200
                assert legacy.json() == {"legacy_overview": True}
                assert manager_calls == 1
                assert len(source_session.account_reads) == 4
        finally:
            configure_service_read(None)
            await worker.aclose()
            await engine.dispose()

    asyncio.run(scenario())
