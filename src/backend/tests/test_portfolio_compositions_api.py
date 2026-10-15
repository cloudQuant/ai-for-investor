"""Deterministic HTTP projection evidence for source-separated memberships."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
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
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.api.portfolio import api as portfolio_api  # noqa: E402
from app.api.portfolio import router as portfolio_router  # noqa: E402
from app.api.service_read import configure_service_read  # noqa: E402
from app.db.database import get_db  # noqa: E402
from app.models.asset_research import AssetAnalysisReport, AssetAnalysisTask  # noqa: E402
from app.models.portfolio_composition import PortfolioCompositionVersion  # noqa: E402
from app.schemas.auth import TokenPayload  # noqa: E402
from app.services.asset_research.data import canonical_json_hash  # noqa: E402
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
            await connection.run_sync(AssetAnalysisTask.__table__.create)
            await connection.run_sync(AssetAnalysisReport.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        report_time = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)

        def report_rows(report_id: str, task_id: str, user_id: str, canonical_id: str):
            sections = {
                "meta": {"asset_type": "stock", "canonical_id": canonical_id},
                "published_decision": {
                    "asset_type": "stock",
                    "market_view": "BULLISH",
                    "normalized_direction": "LONG",
                    "recommendation": "BUY",
                    "actionability": "RESEARCH_ONLY",
                    "quality_status": "ELIGIBLE",
                    "horizon_code": "1d",
                    "execution_disabled": True,
                    "expected_return": 999.0,
                },
                "candidate_decision": {"recommendation": "MUST_NOT_LEAK"},
                "sections": [],
            }
            task = AssetAnalysisTask(
                id=task_id,
                user_id=user_id,
                owner_scope="USER",
                instrument_id=f"instrument-{task_id}",
                asset_type="stock",
                canonical_id=canonical_id,
                identity_version="synthetic-v1",
                request_json={},
                position_context="UNKNOWN",
                horizon_code="1d",
                status="SUCCEEDED",
                progress=100,
                created_at=report_time,
                completed_at=report_time,
            )
            report = AssetAnalysisReport(
                id=report_id,
                task_id=task_id,
                prediction_id=None,
                report_version="v1",
                sections_json=sections,
                rendered_markdown="synthetic report body is not projected",
                content_hash=canonical_json_hash(sections),
                created_at=report_time,
            )
            return task, report

        owner_report_id = "report-owner-a"
        other_owner_report_id = "report-owner-b"
        corrupt_report_id = "report-corrupt"
        owner_task, owner_report = report_rows(
            owner_report_id, "task-owner-a", "owner-a", "SYNTH:AAA"
        )
        other_task, other_report = report_rows(
            other_owner_report_id, "task-owner-b", "owner-b", "SYNTH:SECRET"
        )
        corrupt_task, corrupt_report = report_rows(
            corrupt_report_id, "task-corrupt", "owner-a", "SYNTH:CORRUPT"
        )
        corrupt_report.content_hash = "0" * 64
        async with session_maker() as source_db:
            source_db.add_all(
                [owner_task, owner_report, other_task, other_report, corrupt_task, corrupt_report]
            )
            await source_db.commit()
            report_count_before_projection = await source_db.scalar(
                select(func.count()).select_from(AssetAnalysisReport)
            )
            task_count_before_projection = await source_db.scalar(
                select(func.count()).select_from(AssetAnalysisTask)
            )

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

                research_request = {
                    "portfolio_ref": "research-report-view",
                    "source_type": "research",
                    "base_currency": "USD",
                    "members": [{"kind": "research_artifact", "ref": owner_report_id}],
                }
                created_research = await client.post(
                    "/api/v1/portfolio/compositions", json=research_request
                )
                assert created_research.status_code == 201, created_research.text
                research_projection = await client.get(
                    "/api/v1/portfolio/overview",
                    params={"portfolio_ref": "research-report-view", "membership_version": 1},
                )
                assert research_projection.status_code == 200, research_projection.text
                research = research_projection.json()
                assert research["source_status"] == "research_reports_projected"
                assert research["source_facts"]["kind"] == "asset_research_reports"
                assert research["source_facts"]["freshness_status"] == "not_defined"
                assert research["source_facts"]["currency_status"] == "not_declared"
                artifact = research["source_facts"]["artifacts"][0]
                assert artifact["status"] == "available"
                assert artifact["report_integrity_status"] == "verified"
                assert artifact["canonical_id"] == "SYNTH:AAA"
                assert artifact["freshness_status"] == "not_defined"
                assert artifact["currency"] is None
                assert artifact["currency_status"] == "not_declared"
                assert artifact["account_value_status"] == "not_applicable_research"
                assert artifact["published_decision"] == {
                    "asset_type": "stock",
                    "market_view": "BULLISH",
                    "normalized_direction": "LONG",
                    "recommendation": "BUY",
                    "actionability": "RESEARCH_ONLY",
                    "quality_status": "ELIGIBLE",
                    "horizon_code": "1d",
                    "execution_disabled": True,
                }
                assert research["account_total"] == {
                    "status": "not_applicable_research",
                    "currency": None,
                    "value": None,
                }
                assert research["accounts"] == []
                assert research["strategies"] == []
                assert research["coverage"]["complete"] is False
                assert "MUST_NOT_LEAK" not in research_projection.text
                assert "expected_return" not in research_projection.text
                assert "rendered_markdown" not in research_projection.text
                assert "storage_uri" not in research_projection.text
                assert manager_calls == 0

                unavailable_request = {
                    **research_request,
                    "portfolio_ref": "research-private-refs",
                    "members": [
                        {"kind": "research_artifact", "ref": other_owner_report_id},
                        {"kind": "research_artifact", "ref": "report-does-not-exist"},
                    ],
                }
                unavailable_create = await client.post(
                    "/api/v1/portfolio/compositions", json=unavailable_request
                )
                assert unavailable_create.status_code == 201, unavailable_create.text
                unavailable_response = await client.get(
                    "/api/v1/portfolio/overview",
                    params={"portfolio_ref": "research-private-refs", "membership_version": 1},
                )
                assert unavailable_response.status_code == 200
                unavailable = unavailable_response.json()
                unavailable_artifacts = unavailable["source_facts"]["artifacts"]
                assert [item["status"] for item in unavailable_artifacts] == [
                    "missing_or_not_owned",
                    "missing_or_not_owned",
                ]
                assert unavailable_artifacts[0] == unavailable_artifacts[1]
                assert "SYNTH:SECRET" not in unavailable_response.text
                assert other_report.content_hash not in unavailable_response.text
                assert unavailable["account_total"]["value"] is None
                assert unavailable["coverage"]["complete"] is False

                corrupt_request = {
                    **research_request,
                    "portfolio_ref": "research-corrupt-report",
                    "members": [{"kind": "research_artifact", "ref": corrupt_report_id}],
                }
                corrupt_create = await client.post(
                    "/api/v1/portfolio/compositions", json=corrupt_request
                )
                assert corrupt_create.status_code == 201
                corrupt_response = await client.get(
                    "/api/v1/portfolio/overview",
                    params={"portfolio_ref": "research-corrupt-report", "membership_version": 1},
                )
                assert corrupt_response.status_code == 200
                corrupt = corrupt_response.json()["source_facts"]["artifacts"][0]
                assert corrupt["status"] == "integrity_invalid"
                assert corrupt["report_integrity_status"] == "invalid"
                assert corrupt["canonical_id"] is None
                assert corrupt["published_decision"] is None
                assert corrupt["currency"] is None
                assert manager_calls == 0

                async with session_maker() as source_db:
                    assert (
                        await source_db.scalar(
                            select(func.count()).select_from(AssetAnalysisReport)
                        )
                        == report_count_before_projection
                    )
                    assert (
                        await source_db.scalar(select(func.count()).select_from(AssetAnalysisTask))
                        == task_count_before_projection
                    )

                first_page = await client.get(
                    "/api/v1/portfolio/compositions", params={"page": 1, "page_size": 2}
                )
                assert first_page.status_code == 200, first_page.text
                first_page_body = first_page.json()
                assert first_page_body["total"] == 8
                assert first_page_body["page"] == 1
                assert first_page_body["page_size"] == 2
                assert first_page_body["has_more"] is True
                assert len(first_page_body["items"]) == 2
                assert all("members" not in item for item in first_page_body["items"])
                assert all("owner_subject" not in item for item in first_page_body["items"])

                second_page = await client.get(
                    "/api/v1/portfolio/compositions", params={"page": 2, "page_size": 2}
                )
                third_page = await client.get(
                    "/api/v1/portfolio/compositions", params={"page": 3, "page_size": 2}
                )
                fourth_page = await client.get(
                    "/api/v1/portfolio/compositions", params={"page": 4, "page_size": 2}
                )
                assert second_page.status_code == third_page.status_code == 200
                assert fourth_page.status_code == 200
                owner_a_items = [
                    *first_page_body["items"],
                    *second_page.json()["items"],
                    *third_page.json()["items"],
                    *fourth_page.json()["items"],
                ]
                assert len(owner_a_items) == 8
                assert {item["portfolio_ref"] for item in owner_a_items} == {
                    "primary",
                    "overlap-view",
                    "imported-view",
                    "paper-view",
                    "research-report-view",
                    "research-private-refs",
                    "research-corrupt-report",
                }
                assert [
                    item["membership_version"]
                    for item in owner_a_items
                    if item["portfolio_ref"] == "primary"
                ] == [2, 1]
                assert fourth_page.json()["has_more"] is False
                assert "account-a" not in (
                    first_page.text + second_page.text + third_page.text + fourth_page.text
                )

                invalid_page_size = await client.get(
                    "/api/v1/portfolio/compositions", params={"page_size": 101}
                )
                assert invalid_page_size.status_code == 422

                app.dependency_overrides[get_current_user] = lambda: TokenPayload(
                    sub="owner-b", username="other"
                )
                empty_owner_b = await client.get("/api/v1/portfolio/compositions")
                assert empty_owner_b.status_code == 200
                assert empty_owner_b.json()["items"] == []
                assert empty_owner_b.json()["total"] == 0

                private_create = await client.post(
                    "/api/v1/portfolio/compositions",
                    json={
                        "portfolio_ref": "private-b",
                        "source_type": "research",
                        "base_currency": "USD",
                        "members": [{"kind": "research_artifact", "ref": "owner-b-artifact"}],
                    },
                )
                assert private_create.status_code == 201, private_create.text
                owner_b_list = await client.get("/api/v1/portfolio/compositions")
                assert owner_b_list.status_code == 200
                assert owner_b_list.json()["total"] == 1
                assert [item["portfolio_ref"] for item in owner_b_list.json()["items"]] == [
                    "private-b"
                ]
                assert "primary" not in owner_b_list.text
                assert "owner-b-artifact" not in owner_b_list.text
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
