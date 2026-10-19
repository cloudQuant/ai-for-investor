"""FastAPI evidence for independent live-account cuts and time skew reporting."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("SECRET_KEY", "synthetic-portfolio-cut-test-secret-20261016")

# Keep this focused API test away from either repository's dotenv files.
from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import get_current_user  # noqa: E402
from app.api.portfolio import router as portfolio_router  # noqa: E402
from app.api.service_read import configure_service_read  # noqa: E402
from app.db.database import get_db  # noqa: E402
from app.models.portfolio_composition import PortfolioCompositionVersion  # noqa: E402
from app.schemas.auth import TokenPayload  # noqa: E402
from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory  # noqa: E402
from app.services.service_read.contracts import AccountReadView, ReadQuality  # noqa: E402
from app.services.service_read.worker import ServiceReadWorker  # noqa: E402


class _SyntheticAccountSession:
    """Supply typed account leaves through the production ServiceReadWorker."""

    def __init__(self, views: dict[str, AccountReadView]) -> None:
        self.views = views
        self.reads: list[tuple[str, str | None]] = []

    def start(self) -> None:
        pass

    def maintain(self) -> None:
        pass

    def read_account(self, account_ref: str, *, currency: str | None = None) -> AccountReadView:
        self.reads.append((account_ref, currency))
        return self.views[account_ref]

    def read_account_book(self, account_ref: str) -> None:
        raise AssertionError(f"unexpected account-book read: {account_ref}")

    def read_order(self, scope_ref: str, intent_id: str) -> None:
        raise AssertionError("unexpected order read")

    def read_strategy_health(self, scope_ref: str) -> None:
        raise AssertionError("unexpected strategy-health read")

    def submit_manual_order(self, scope_ref: str, arguments: dict[str, Any]) -> Any:
        raise AssertionError("unexpected manual-order submission")

    def submit_approved_target(self, scope_ref: str, arguments: dict[str, Any]) -> Any:
        raise AssertionError("unexpected approved-target submission")

    def close(self) -> None:
        pass


def _account_key(account_id: str) -> Any:
    try:
        from bt_api_base.account_protocol import AccountKey
    except ImportError:
        pytest.skip("the service SDK account protocol is not installed")
    return AccountKey(
        provider="synthetic-provider",
        venue="synthetic-venue",
        environment="live",
        account_id=account_id,
        subaccount_id=None,
    )


def _account_view(
    account_ref: str,
    *,
    account_id: str,
    value: str | None,
    cash: str | None,
    observed_at_utc: str | None,
    cursor: int | None,
    session_generation: str | None,
    quality: ReadQuality = ReadQuality.FRESH,
    source_service_id: str | None = None,
    detail_code: str | None = None,
) -> AccountReadView:
    key = _account_key(account_id)
    return AccountReadView(
        account_ref=account_ref,
        execution_domain_ref="live:synthetic-venue",
        currency="USD",
        quality=quality,
        source_service_id=source_service_id,
        session_generation=session_generation,
        cursor=cursor,
        cash=Decimal(cash) if cash is not None else None,
        value=Decimal(value) if value is not None else None,
        observed_at_utc=observed_at_utc,
        received_age_seconds=0.25 if quality is ReadQuality.FRESH else None,
        fresh_for_seconds=5.0 if quality is ReadQuality.FRESH else None,
        detail_code=detail_code,
        account_key=key.to_dict(),
        account_key_id=key.account_key_id,
        positions_count=3 if quality is ReadQuality.FRESH else None,
        open_orders_count=2 if quality is ReadQuality.FRESH else None,
    )


def _read_live_projection(views: dict[str, AccountReadView]) -> dict[str, Any]:
    async def scenario() -> dict[str, Any]:
        owner = TokenPayload(sub="cut-owner", username="owner")
        source_session = _SyntheticAccountSession(views)
        worker = ServiceReadWorker(
            lambda: source_session,
            maintenance_interval_seconds=60,
            name="afi-independent-account-cut-api",
        )
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(PortfolioCompositionVersion.__table__.create)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        members = [{"kind": "account", "ref": account_ref} for account_ref in views]
        async with session_maker() as db:
            db.add(
                PortfolioCompositionVersion(
                    owner_subject=owner.sub,
                    portfolio_ref="cut-matrix",
                    membership_version=1,
                    source_type="live",
                    base_currency="USD",
                    members=members,
                    membership_sha256="c" * 64,
                )
            )
            await db.commit()

        app = FastAPI()
        app.include_router(portfolio_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: owner

        async def override_db() -> AsyncIterator[AsyncSession]:
            async with session_maker() as session:
                yield session

        app.dependency_overrides[get_db] = override_db
        configure_service_read(
            ServiceReadAccessDirectory(
                {
                    owner.sub: ReadAccess(
                        worker,
                        allow_account_refs=set(views),
                    )
                }
            )
        )
        try:
            await worker.start()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/api/v1/portfolio/compositions/cut-matrix/versions/1/projection"
                )
            assert response.status_code == 200, response.text
            assert source_session.reads == [(ref, "USD") for ref in views]
            return response.json()
        finally:
            configure_service_read(None)
            await worker.aclose()
            await engine.dispose()

    return asyncio.run(scenario())


@pytest.mark.parametrize(
    ("times", "expected_status", "expected_skew_ns"),
    [
        (
            (
                "2026-10-16T08:00:00.123456789Z",
                "2026-10-16T16:00:00.123456789+08:00",
            ),
            "same_observation_time_independent_cuts",
            "0",
        ),
        (
            ("2026-10-16T08:00:00.123456789Z", "2026-10-16T08:00:02.223456790Z"),
            "different_observation_times_independent_cuts",
            "2100000001",
        ),
    ],
    ids=("same-observation-time", "different-observation-time"),
)
def test_live_composition_api_reports_independent_account_cuts_and_exact_skew(
    times: tuple[str, str], expected_status: str, expected_skew_ns: str
) -> None:
    projection = _read_live_projection(
        {
            "account-a": _account_view(
                "account-a",
                account_id="synthetic-a",
                value="100",
                cash="80",
                observed_at_utc=times[0],
                cursor=0,
                session_generation="generation-a",
                source_service_id="service-a",
            ),
            "account-b": _account_view(
                "account-b",
                account_id="synthetic-b",
                value="200",
                cash="150",
                observed_at_utc=times[1],
                cursor=7,
                session_generation="generation-b",
                source_service_id="service-b",
            ),
        }
    )

    assert projection["account_total"] == {
        "status": "current",
        "currency": "USD",
        "value": "300",
    }
    rows = {row["member_ref"]: row for row in projection["accounts"]}
    assert rows["account-a"]["cursor"] == 0
    assert rows["account-a"]["account_ref"] == "account-a"
    assert rows["account-a"]["session_generation"] == "generation-a"
    assert rows["account-a"]["source_service_id"] == "service-a"
    assert rows["account-a"]["observed_at_utc"] == times[0]
    assert rows["account-a"]["has_current_facts"] is True
    assert rows["account-a"]["positions_count"] == 3
    assert rows["account-a"]["open_orders_count"] == 2
    assert rows["account-b"]["cursor"] == 7
    assert rows["account-b"]["session_generation"] == "generation-b"
    assert rows["account-b"]["source_service_id"] == "service-b"
    assert rows["account-b"]["observed_at_utc"] == times[1]
    assert all(
        "account_key" not in row and "account_key_id" not in row
        for row in rows.values()
    )

    consistency = projection["account_snapshot_consistency"]
    assert consistency["cut_model"] == "independent_per_account"
    assert consistency["atomic"] is False
    assert consistency["member_read_count"] == 2
    assert consistency["observed_at_count"] == 2
    assert consistency["status"] == expected_status
    assert consistency["skew_ns"] == expected_skew_ns
    assert consistency["skew_policy"] == "reported_without_threshold"


def test_live_composition_api_keeps_missing_cut_fields_distinct_from_zero_cursor() -> None:
    missing = _account_view(
        "account-a",
        account_id="synthetic-a",
        value=None,
        cash=None,
        observed_at_utc=None,
        cursor=None,
        session_generation=None,
        quality=ReadQuality.NOT_COLLECTED,
        source_service_id=None,
        detail_code="CURRENCY_NOT_OBSERVED",
    )
    zero = _account_view(
        "account-b",
        account_id="synthetic-b",
        value="0",
        cash="0",
        observed_at_utc="2026-10-16T08:00:00Z",
        cursor=0,
        session_generation="generation-b",
        source_service_id="service-b",
    )

    projection = _read_live_projection({"account-a": missing, "account-b": zero})
    assert projection["account_total"] == {
        "status": "incomplete",
        "currency": "USD",
        "value": None,
    }
    rows = {row["member_ref"]: row for row in projection["accounts"]}
    assert rows["account-a"]["quality"] == "not_collected"
    assert rows["account-a"]["has_current_facts"] is False
    assert rows["account-a"]["cash"] is None
    assert rows["account-a"]["value"] is None
    assert rows["account-a"]["positions_count"] is None
    assert rows["account-a"]["open_orders_count"] is None
    assert rows["account-a"]["cursor"] is None
    assert rows["account-a"]["session_generation"] is None
    assert rows["account-a"]["source_service_id"] is None
    assert rows["account-a"]["observed_at_utc"] is None
    assert rows["account-a"]["detail_code"] == "CURRENCY_NOT_OBSERVED"
    assert rows["account-b"]["quality"] == "fresh"
    assert rows["account-b"]["cash"] == "0"
    assert rows["account-b"]["value"] == "0"
    assert rows["account-b"]["has_current_facts"] is True
    assert rows["account-b"]["positions_count"] == 3
    assert rows["account-b"]["open_orders_count"] == 2
    assert rows["account-b"]["cursor"] == 0

    consistency = projection["account_snapshot_consistency"]
    assert consistency["cut_model"] == "independent_per_account"
    assert consistency["atomic"] is False
    assert consistency["status"] == "observation_time_incomplete"
    assert consistency["member_read_count"] == 2
    assert consistency["observed_at_count"] == 1
    assert consistency["skew_ns"] is None
    assert consistency["skew_policy"] == "reported_without_threshold"
