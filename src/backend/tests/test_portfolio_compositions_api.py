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
from app.models.portfolio_ledger import PortfolioLedgerImportModel, PortfolioLedgerModel  # noqa: E402
from app.models.strategy_approval_authority import StrategyApprovalAuthorityEpoch  # noqa: E402
from app.schemas.auth import TokenPayload  # noqa: E402
from app.services.asset_research.data import canonical_json_hash  # noqa: E402
from app.services.portfolio_composition import _public_financial_projection  # noqa: E402
from app.services.service_read.access import (  # noqa: E402
    ReadAccess,
    ServiceReadAccessDirectory,
    StrategyBookBinding,
)
from app.services.service_read.contracts import (  # noqa: E402
    AccountBookReadView,
    AccountReadView,
    ReadQuality,
)
from app.services.service_read.worker import ServiceReadWorker  # noqa: E402


class _SyntheticReadSession:
    def __init__(
        self,
        views: dict[str, AccountReadView],
        account_book_views: dict[str, AccountBookReadView] | None = None,
    ) -> None:
        self.views = views
        self.account_book_views = account_book_views or {}
        self.account_reads: list[tuple[str, str | None]] = []
        self.account_book_reads: list[str] = []
        self.closed = False

    def start(self) -> None:
        pass

    def maintain(self) -> None:
        pass

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        self.account_reads.append((account_ref, currency))
        return self.views[account_ref]

    def read_account_book(self, account_ref: str) -> AccountBookReadView:
        self.account_book_reads.append(account_ref)
        return self.account_book_views[account_ref]

    def read_order(self, scope_ref: str, intent_id: str) -> None:
        raise AssertionError("the composition projection must not read orders")

    def read_strategy_health(self, scope_ref: str) -> None:
        raise AssertionError("health is not execution attribution")

    def close(self) -> None:
        self.closed = True


def _account_view(
    account_ref: str,
    key: object,
    *,
    value: str,
    cash: str,
    provider_observation: dict | None = None,
) -> AccountReadView:
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
        provider_observation=provider_observation,
    )


def test_public_account_book_projection_preserves_financial_states_and_hides_internal_keys():
    base_source = {
        "state": "RESIDUAL",
        "coverage": {
            "account_key": "private-account-key",
            "complete": True,
            "current_execution_cursor": 7,
        },
        "books": [
            {
                "owner_kind": "UNALLOCATED",
                "owner_ref": "UNALLOCATED",
                "current_positions": [],
                "fees_since_baseline": [],
            }
        ],
        "provider_position_change": [],
        "position_residual": [],
        "fee_residual": [],
    }

    absent = _public_financial_projection(base_source)
    assert absent == {"status": "absent"}

    unavailable_source = {
        **base_source,
        "financial": {
            "available": False,
            "code": "PERSISTED_PROJECTION_UNAVAILABLE",
            "freshness": "NOT_ESTABLISHED",
            "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
            "account_key": "private-account-key",
        },
    }
    unavailable = _public_financial_projection(unavailable_source)
    assert unavailable == {
        "status": "unavailable",
        "code": "PERSISTED_PROJECTION_UNAVAILABLE",
        "freshness": "NOT_ESTABLISHED",
        "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
    }

    captured_at_ns = 1_797_000_000_123_456_789
    ledger_cut = {
        "account_key": "private-account-key",
        "owner_directory_revision": "directory-r3",
        "captured_at_ns": captured_at_ns,
        "watermarks": [
            {
                "source_kind": source_kind,
                "source_ref": f"synthetic-{source_kind}",
                "generation": f"generation-{source_kind}",
                "cursor": cursor,
                "as_of_ns": captured_at_ns,
            }
            for source_kind, cursor in (
                ("execution_outbox", 7),
                ("account_facts", 8),
                ("account_activity", 9),
            )
        ],
    }
    available_source = {
        **base_source,
        "financial": {
            "available": True,
            "source": "PERSISTED_EXECUTION_FINANCIAL_PROJECTION",
            "freshness": "PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED",
            "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
            "complete": True,
            "state": "RESIDUAL",
            "ledger_cut": ledger_cut,
            "books": [
                {
                    "owner": {
                        "kind": "STRATEGY",
                        "owner_ref": "strategy-a",
                        "execution_scope_key": "private-execution-scope",
                    },
                    "ledger_cut": ledger_cut,
                    "cash": [{"currency": "USD", "amount": "0"}],
                    "positions": [
                        {
                            "instrument": "BTC-USD",
                            "quantity": "2",
                            "cost_basis": None,
                            "cost_currency": None,
                            "cost_method": "AVERAGE_COST",
                            "product_model": "SPOT",
                            "metadata_version": "spot-v1",
                        }
                    ],
                    "cumulative_fees": [{"currency": "USD", "amount": "0"}],
                    "realized_pnl": [],
                    "cost_basis_complete": False,
                }
            ],
            "unallocated": {
                "cash": [],
                "positions": [["ETH-USD", "0.5"]],
                "fees": [],
            },
        },
    }
    financial = _public_financial_projection(available_source)
    assert financial["status"] == "available"
    assert financial["complete"] is True
    assert financial["cut_relationship"] == "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT"
    assert financial["ledger_cut"]["captured_at_ns"] == str(captured_at_ns)
    assert financial["ledger_cut"]["watermarks"][0]["as_of_ns"] == str(captured_at_ns)
    assert financial["books"][0]["cash"] == [{"currency": "USD", "amount": "0"}]
    assert financial["books"][0]["positions"][0]["cost_basis"] is None
    assert financial["unallocated"]["positions"] == [
        {"instrument": "ETH-USD", "quantity": "0.5"}
    ]
    assert "account_key" not in financial["ledger_cut"]
    assert "execution_scope_key" not in financial["books"][0]["owner"]
    assert "private-account-key" not in repr(financial)
    assert "private-execution-scope" not in repr(financial)


def test_financial_projection_reaches_composition_http_response():
    try:
        from bt_api_base.account_protocol import AccountKey
    except ImportError:
        pytest.skip("the service SDK account protocol is not installed")

    async def scenario() -> None:
        owner = TokenPayload(sub="financial-owner", username="owner")
        account_ref = "account-a"
        strategy_ref = "strategy-a"
        account_key = AccountKey(
            provider="synthetic-provider",
            venue="synthetic-venue",
            environment="live",
            account_id="synthetic-account-a",
            subaccount_id=None,
        )
        account_view = _account_view(
            account_ref, account_key, value="950", cash="200"
        )
        account_book = AccountBookReadView(
            account_ref=account_ref,
            account_key_id=account_key.account_key_id,
            projection={
                "view": "ACCOUNT",
                "coverage": {
                    "account_key": "private-book-key-a",
                    "scope_directory_revision": "legacy-directory-r1",
                    "journal_generation": "legacy-journal-r1",
                    "baseline_execution_cursor": 0,
                    "current_execution_cursor": 0,
                    "complete": False,
                    "reasons": ["ACCOUNT_BOOK_NOT_CONFIGURED"],
                    "scanned_outbox_events": 0,
                    "outbox_history_contiguous": False,
                    "outbox_scan_complete": False,
                    "continuations": [],
                    "input_continuations": [],
                    "quarantined_intents": [],
                },
                "state": "PARTIAL",
                "books": [
                    {
                        "owner_kind": "STRATEGY",
                        "owner_ref": strategy_ref,
                        "current_positions": [],
                        "fees_since_baseline": [],
                    }
                ],
                "managed_orders": [],
                "managed_fills": [],
                "external_orders": [],
                "external_fills": [],
                "provider_position_change": [],
                "position_residual": [],
                "fee_residual": [],
                "financial": {
                    "available": False,
                    "code": "FINANCIAL_DIRECTORY_UNAVAILABLE",
                    "freshness": "NOT_ESTABLISHED",
                    "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
                },
            },
        )
        source_session = _SyntheticReadSession(
            {account_ref: account_view},
            {account_ref: account_book},
        )
        worker = ServiceReadWorker(
            lambda: source_session,
            maintenance_interval_seconds=60,
            name="afi-financial-projection-http-synthetic",
        )
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as db:
            db.add(
                PortfolioCompositionVersion(
                    owner_subject=owner.sub,
                    portfolio_ref="financial-http",
                    membership_version=1,
                    source_type="live",
                    base_currency="USD",
                    members=[
                        {"kind": "account", "ref": account_ref},
                        {"kind": "strategy", "ref": strategy_ref},
                    ],
                    membership_sha256="a" * 64,
                )
            )
            await db.commit()

        app = FastAPI()
        app.include_router(portfolio_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: owner

        async def override_db():
            async with session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        configure_service_read(
            ServiceReadAccessDirectory(
                {
                    owner.sub: ReadAccess(
                        worker,
                        allow_account_refs={account_ref},
                        allow_account_book_refs={account_ref},
                        strategy_book_bindings={
                            strategy_ref: StrategyBookBinding(
                                account_ref=account_ref,
                                owner_ref=strategy_ref,
                            )
                        },
                    )
                }
            )
        )
        try:
            await worker.start()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/portfolio/compositions/financial-http/versions/1/projection"
                )
            assert response.status_code == 200, response.text
            projected = response.json()
            assert projected["account_total"] == {
                "status": "current",
                "currency": "USD",
                "value": "950",
            }
            financial = projected["account_book_sources"][0]["financial"]
            assert financial == {
                "status": "unavailable",
                "code": "FINANCIAL_DIRECTORY_UNAVAILABLE",
                "freshness": "NOT_ESTABLISHED",
                "cut_relationship": "INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT",
            }
            assert source_session.account_book_reads == [account_ref]
            for private_value in ("private-book-key-a", "synthetic-account-a"):
                assert private_value not in response.text
        finally:
            configure_service_read(None)
            await worker.aclose()
            await engine.dispose()

    asyncio.run(scenario())


def test_provider_observations_reach_live_composition_http_without_fx_or_account_key():
    try:
        from bt_api_base.account_protocol import AccountKey
    except ImportError:
        pytest.skip("the service SDK account protocol is not installed")

    async def scenario() -> None:
        owner = TokenPayload(sub="observation-owner", username="owner")
        resource = {"product_type": "SPOT", "margin_pool": "cash"}
        funding_resource = {"product_type": "SPOT", "margin_pool": "funding"}
        account_a_key = AccountKey(
            provider="synthetic-provider",
            venue="synthetic-venue",
            environment="live",
            account_id="private-synthetic-account-a",
            subaccount_id=None,
        )
        account_b_key = AccountKey(
            provider="synthetic-provider",
            venue="synthetic-venue",
            environment="live",
            account_id="private-synthetic-account-b",
            subaccount_id=None,
        )
        observation_a = {
            "observation_id": "observation-a",
            "coverage": [resource, funding_resource],
            "balances": [
                {
                    "resource": resource,
                    "currency": "USD",
                    "total": "100",
                    "available": "20",
                    "locked": "80",
                    "observed_at_utc": "2026-10-15T00:00:00Z",
                },
                {
                    "resource": resource,
                    "currency": "EUR",
                    "total": "12.5",
                    "available": None,
                    "locked": "0",
                    "observed_at_utc": "2026-10-15T00:00:00.5Z",
                },
                {
                    "resource": funding_resource,
                    "currency": "USDT",
                    "total": "0",
                    "available": "0",
                    "locked": "0",
                    "observed_at_utc": "2026-10-15T00:00:00Z",
                },
            ],
            "positions": [
                {
                    "resource": resource,
                    "instrument": {
                        "provider": account_a_key.provider,
                        "venue": account_a_key.venue,
                        "environment": account_a_key.environment,
                        "product_type": "SPOT",
                        "instrument_id": "instrument-zero",
                        "native_symbol": "ZERO/EUR",
                    },
                    "side": "net",
                    "quantity": "0",
                    "qty_unit": "base_asset",
                    "average_price": "0",
                    "price_currency": "EUR",
                    "observed_at_utc": "2026-10-15T00:00:01Z",
                },
                {
                    "resource": resource,
                    "instrument": {
                        "provider": account_a_key.provider,
                        "venue": account_a_key.venue,
                        "environment": account_a_key.environment,
                        "product_type": "SPOT",
                        "instrument_id": "instrument-missing-price",
                        "native_symbol": "NO-MARK/EUR",
                    },
                    "side": "long",
                    "quantity": "2",
                    "qty_unit": "contracts",
                    "average_price": None,
                    "price_currency": None,
                    "observed_at_utc": "2026-10-15T00:00:01Z",
                },
            ],
            "valuation": None,
            "started_at_utc": "2026-10-15T00:00:00Z",
            "completed_at_utc": "2026-10-15T00:00:01Z",
            "consistency": "multi_query",
            "balances_complete": False,
            "positions_complete": True,
        }
        observation_b = {
            "observation_id": "observation-b",
            "coverage": [resource],
            "balances": [
                {
                    "resource": resource,
                    "currency": "USD",
                    "total": "5",
                    "available": "1",
                    "locked": "4",
                    "observed_at_utc": "2026-10-15T00:00:02Z",
                }
            ],
            "positions": [],
            "valuation": None,
            "started_at_utc": "2026-10-15T00:00:02Z",
            "completed_at_utc": "2026-10-15T00:00:03Z",
            "consistency": "provider_atomic",
            "balances_complete": True,
            "positions_complete": True,
        }
        views = {
            "account-a": _account_view(
                "account-a",
                account_a_key,
                value="100",
                cash="20",
                provider_observation=observation_a,
            ),
            "account-b": _account_view(
                "account-b",
                account_b_key,
                value="5",
                cash="1",
                provider_observation=observation_b,
            ),
        }
        source_session = _SyntheticReadSession(views)
        worker = ServiceReadWorker(
            lambda: source_session,
            maintenance_interval_seconds=60,
            name="afi-provider-observation-http-synthetic",
        )
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        async with session_maker() as db:
            db.add(
                PortfolioCompositionVersion(
                    owner_subject=owner.sub,
                    portfolio_ref="provider-observation-http",
                    membership_version=1,
                    source_type="live",
                    base_currency="USD",
                    members=[
                        {"kind": "account", "ref": "account-a"},
                        {"kind": "account", "ref": "account-b"},
                    ],
                    membership_sha256="b" * 64,
                )
            )
            await db.commit()

        app = FastAPI()
        app.include_router(portfolio_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: owner

        async def override_db():
            async with session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        configure_service_read(
            ServiceReadAccessDirectory(
                {
                    owner.sub: ReadAccess(
                        worker,
                        allow_account_refs={"account-a", "account-b"},
                    )
                }
            )
        )
        try:
            await worker.start()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/portfolio/compositions/provider-observation-http/versions/1/projection"
                )
            assert response.status_code == 200, response.text
            projected = response.json()
            # The portfolio total remains the authorized account-level USD figure.
            # EUR balance rows and position facts never enter this aggregate.
            assert projected["account_total"] == {
                "status": "current",
                "currency": "USD",
                "value": "105",
            }
            account_a = projected["accounts"][0]["provider_observation"]
            assert "account_key" not in account_a
            assert "account_key_id" not in account_a
            assert account_a["status"] == "available"
            assert account_a["coverage"]["state"] == "incomplete"
            assert [row["currency"] for row in account_a["balances"]] == [
                "USD",
                "EUR",
                "USDT",
            ]
            assert account_a["balances"][0]["total"] == "100"
            assert account_a["balances"][1]["total"] == "12.5"
            assert account_a["balances"][1]["available"] is None
            assert account_a["balances"][2]["total"] == "0"
            assert account_a["positions"][0]["quantity"] == "0"
            assert account_a["positions"][0]["average_price"] == "0"
            assert account_a["positions"][1]["quantity"] == "2"
            assert account_a["positions"][1]["average_price"] is None
            assert account_a["positions"][1]["instrument"] == {
                "provider": "synthetic-provider",
                "venue": "synthetic-venue",
                "environment": "live",
                "product_type": "SPOT",
                "instrument_id": "instrument-missing-price",
                "native_symbol": "NO-MARK/EUR",
            }
            assert account_a["positions"][1]["valuation_inputs"] == {
                "mark_price": {"status": "missing", "value": None},
                "contract_multiplier": {"status": "unsupported", "value": None},
                "fx_rate": {"status": "unsupported", "value": None},
                "market_value": {"status": "not_calculated", "value": None},
            }
            consistency = projected["provider_snapshot_consistency"]
            assert consistency["cut_model"] == "independent_provider_observation_per_account"
            assert consistency["atomic"] is False
            assert consistency["skew_ns"] == "2000000000"
            assert consistency["coverage_status"] == "incomplete"
            assert consistency["status"] == "different_completion_times_independent_cuts"
            assert source_session.account_book_reads == []
            for private_value in (
                account_a_key.account_id,
                account_b_key.account_id,
                account_a_key.account_key_id,
                account_b_key.account_key_id,
            ):
                assert private_value not in response.text
        finally:
            configure_service_read(None)
            await worker.aclose()
            await engine.dispose()

    asyncio.run(scenario())


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
            await connection.run_sync(StrategyApprovalAuthorityEpoch.__table__.create)
            await connection.run_sync(AssetAnalysisTask.__table__.create)
            await connection.run_sync(AssetAnalysisReport.__table__.create)
            await connection.run_sync(PortfolioLedgerModel.__table__.create)
            await connection.run_sync(PortfolioLedgerImportModel.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        async with session_maker() as source_db:
            source_db.add(
                PortfolioLedgerModel(
                    id="ledger-owner-a",
                    owner_id="owner-a",
                    name="legacy imported ledger",
                    base_currency="USD",
                    source_type="imported",
                )
            )
            source_db.add(
                PortfolioLedgerImportModel(
                    id="ledger-1",
                    portfolio_id="ledger-owner-a",
                    import_format="json",
                    idempotency_key="legacy-import-key",
                    imported_count=1,
                )
            )
            await source_db.commit()

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

                versions_before_denial = await client.get("/api/v1/portfolio/compositions")
                assert versions_before_denial.status_code == 200
                assert versions_before_denial.json()["total"] == 1
                unauthorized = {
                    **live_request,
                    "portfolio_ref": "not-authorized",
                    "members": [{"kind": "account", "ref": "account-outside-grant"}],
                }
                denied = await client.post("/api/v1/portfolio/compositions", json=unauthorized)
                assert denied.status_code == 403
                assert denied.json() == {
                    "detail": {
                        "code": "SERVICE_READ_ACCESS_DENIED",
                        "message": "The requested service-read scope is not authorized.",
                    }
                }
                assert "account-outside-grant" not in denied.text
                versions_after_denial = await client.get("/api/v1/portfolio/compositions")
                assert versions_after_denial.status_code == 200
                assert versions_after_denial.json()["total"] == 1
                assert "not-authorized" not in versions_after_denial.text

                unbound_strategy = {
                    **live_request,
                    "portfolio_ref": "unbound-strategy",
                    "members": [
                        {"kind": "account", "ref": "account-a"},
                        {"kind": "strategy", "ref": "strategy-outside-grant"},
                    ],
                }
                denied_strategy = await client.post(
                    "/api/v1/portfolio/compositions", json=unbound_strategy
                )
                assert denied_strategy.status_code == 403
                assert denied_strategy.json() == denied.json()
                assert "strategy-outside-grant" not in denied_strategy.text
                versions_after_strategy_denial = await client.get(
                    "/api/v1/portfolio/compositions"
                )
                assert versions_after_strategy_denial.status_code == 200
                assert versions_after_strategy_denial.json()["total"] == 1
                assert "unbound-strategy" not in versions_after_strategy_denial.text
                assert "strategy-outside-grant" not in versions_after_strategy_denial.text

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
                assert live["strategies"] == []
                assert live["strategy_attribution"]["strategy_count"] == 0
                assert live["coverage"]["account_facts_complete"] is True
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

                created_legacy_imported = await client.post(
                    "/api/v1/portfolio/compositions",
                    json={
                        "portfolio_ref": "imported-view",
                        "source_type": "imported",
                        "base_currency": "USD",
                        "members": [{"kind": "imported_ledger", "ref": "ledger-1"}],
                    },
                )
                assert created_legacy_imported.status_code == 201, created_legacy_imported.text
                legacy_import_projection = await client.get(
                    "/api/v1/portfolio/compositions/imported-view/versions/1/projection"
                )
                assert legacy_import_projection.status_code == 200
                legacy_imported = legacy_import_projection.json()
                assert legacy_imported["source_status"] == "imported_materials_unavailable"
                assert legacy_imported["source_facts"]["artifacts"][0]["status"] == (
                    "source_material_unavailable"
                )
                assert legacy_imported["account_total"] == {
                    "status": "not_applicable_imported",
                    "currency": None,
                    "value": None,
                }
                assert legacy_imported["coverage"]["complete"] is False
                assert legacy_imported["creditable"] is False

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


def test_live_composition_scope_denial_is_private_and_does_not_write():
    """Exercise subject-owned HTTP scopes with real AFI services and synthetic facts only."""

    try:
        from bt_api_base.account_protocol import AccountKey
    except ImportError:
        pytest.skip("the service SDK account protocol is not installed")

    async def scenario() -> None:
        owner_a = TokenPayload(sub="scope-owner-a", username="operator-a")
        owner_b = TokenPayload(sub="scope-owner-b", username="operator-b")
        account_a = "scope-owner-a-account"
        account_b = "scope-owner-b-account"
        strategy_b = "scope-owner-b-strategy"
        account_key_a = AccountKey(
            provider="synthetic-provider",
            venue="synthetic-venue",
            environment="live",
            account_id="private-owner-a-account-id",
            subaccount_id=None,
        )
        source_a = _SyntheticReadSession(
            {account_a: _account_view(account_a, account_key_a, value="100", cash="20")}
        )
        worker_a = ServiceReadWorker(
            lambda: source_a,
            maintenance_interval_seconds=60,
            name="afi-scope-synthetic-owner-a",
        )
        worker_b = ServiceReadWorker(
            lambda: _SyntheticReadSession({}),
            maintenance_interval_seconds=60,
            name="afi-scope-synthetic-owner-b",
        )
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        legacy_members = [
            {"kind": "account", "ref": account_a},
            {"kind": "strategy", "ref": "historical-unbound-strategy"},
        ]

        def version_hash(members: list[dict[str, str]]) -> str:
            return canonical_json_hash(
                {
                    "source_type": "live",
                    "base_currency": "USD",
                    "members": sorted(
                        members, key=lambda member: (member["kind"], member["ref"])
                    ),
                }
            )

        async with session_maker() as session:
            session.add(
                PortfolioCompositionVersion(
                    owner_subject=owner_a.sub,
                    portfolio_ref="legacy-unbound",
                    membership_version=1,
                    source_type="live",
                    base_currency="USD",
                    members=legacy_members,
                    membership_sha256=version_hash(legacy_members),
                )
            )
            await session.commit()

        current_user = {"payload": owner_a}
        app = FastAPI()
        app.include_router(portfolio_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: current_user["payload"]

        async def override_db():
            async with session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        configure_service_read(
            ServiceReadAccessDirectory(
                {
                    owner_a.sub: ReadAccess(worker_a, allow_account_refs={account_a}),
                    owner_b.sub: ReadAccess(
                        worker_b,
                        allow_account_refs={account_b},
                        allow_account_book_refs={account_b},
                        strategy_book_bindings={
                            strategy_b: StrategyBookBinding(
                                account_ref=account_b,
                                owner_ref="scope-owner-b-strategy-owner",
                            )
                        },
                    ),
                }
            )
        )
        try:
            await worker_a.start()
            await worker_b.start()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                before = await client.get("/api/v1/portfolio/compositions")
                assert before.status_code == 200
                assert before.json()["total"] == 1
                async with session_maker() as session:
                    initial_row_count = await session.scalar(
                        select(func.count()).select_from(PortfolioCompositionVersion)
                    )
                assert initial_row_count == 1

                attempts = (
                    (
                        "unknown-account",
                        [{"kind": "account", "ref": "unknown-account-ref"}],
                        ("unknown-account-ref",),
                    ),
                    (
                        "foreign-account",
                        [{"kind": "account", "ref": account_b}],
                        (account_b,),
                    ),
                    (
                        "foreign-strategy",
                        [
                            {"kind": "account", "ref": account_a},
                            {"kind": "strategy", "ref": strategy_b},
                        ],
                        (strategy_b, account_b),
                    ),
                    (
                        "unknown-strategy",
                        [
                            {"kind": "account", "ref": account_a},
                            {"kind": "strategy", "ref": "unknown-strategy-ref"},
                        ],
                        ("unknown-strategy-ref",),
                    ),
                )
                expected_denial = {
                    "detail": {
                        "code": "SERVICE_READ_ACCESS_DENIED",
                        "message": "The requested service-read scope is not authorized.",
                    }
                }
                for portfolio_ref, members, private_refs in attempts:
                    denied = await client.post(
                        "/api/v1/portfolio/compositions",
                        json={
                            "portfolio_ref": portfolio_ref,
                            "source_type": "live",
                            "base_currency": "USD",
                            "members": members,
                        },
                    )
                    assert denied.status_code == 403
                    assert denied.json() == expected_denial
                    assert all(reference not in denied.text for reference in private_refs)

                after = await client.get("/api/v1/portfolio/compositions")
                assert after.status_code == 200
                assert after.json()["total"] == 1
                assert [item["portfolio_ref"] for item in after.json()["items"]] == [
                    "legacy-unbound"
                ]
                assert all(portfolio_ref not in after.text for portfolio_ref, *_ in attempts)
                async with session_maker() as session:
                    stored_row_count = await session.scalar(
                        select(func.count()).select_from(PortfolioCompositionVersion)
                    )
                assert stored_row_count == 1
                assert source_a.account_reads == []

                historical_read = await client.get(
                    "/api/v1/portfolio/compositions/legacy-unbound/versions/1/projection"
                )
                assert historical_read.status_code == 200, historical_read.text
                historical = historical_read.json()
                assert historical["strategy_attribution"]["status"] == (
                    "execution_attribution_not_collected"
                )
                assert historical["strategies"][0]["strategy_ref"] == (
                    "historical-unbound-strategy"
                )
                assert historical["account_total"]["value"] == "100"
                assert account_key_a.account_id not in historical_read.text
                assert account_key_a.account_key_id not in historical_read.text
                assert source_a.account_reads == [(account_a, "USD")]
                assert source_a.account_book_reads == []
        finally:
            configure_service_read(None)
            await worker_a.aclose()
            await worker_b.aclose()
            await engine.dispose()

    asyncio.run(scenario())
