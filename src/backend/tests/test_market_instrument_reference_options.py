"""Offline route composition tests, runnable with --noconftest and no app.main."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import JsonValue
from sqlalchemy import delete, insert, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.data import base
from app.api.data.instrument_reference import (
    InstrumentReferenceCatalog,
    build_instrument_reference_catalog,
    get_instrument_reference_catalog,
    get_instrument_reference_session_factory,
)
from app.api.deps import get_current_user
from app.config import Settings
from app.db.database import Base
from app.models.permission import Role, user_roles
from app.models.user import User
from app.services.market_data.opendata_instrument_reference import InstrumentReferenceError

pytestmark = pytest.mark.asyncio
_USER_ID = "fixture-reference-user"
_FIXTURE = Path(__file__).parent / "fixtures" / "afi204_instrument_reference_v1.json"
_PATH = "/data/market-instruments/options"


@dataclass
class StubReader:
    """An injected reader that can revoke authorization during the external wait."""

    db: AsyncSession
    calls: list[dict[str, object]] = field(default_factory=list)
    action: Callable[[], Awaitable[None]] | None = None
    failure: str | None = None

    async def list_options(
        self, *, search: str = "", limit: int = 80, effective_on: date | None = None
    ) -> dict[str, JsonValue]:
        assert not self.db.in_transaction(), "HTTP must not retain a control DB read transaction"
        self.calls.append({"search": search, "limit": limit, "effective_on": effective_on})
        if self.action is not None:
            await self.action()
        if self.failure:
            raise InstrumentReferenceError(self.failure)
        return json.loads(_FIXTURE.read_text())["options_response"]


@dataclass
class LegacySpy:
    """Record legacy calls without resolving a warehouse or source provider."""

    calls: list[dict[str, object]] = field(default_factory=list)

    async def list_instruments(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        return {"asset_type": kwargs["asset_type"], "items": [], "total": 0}


@dataclass
class Harness:
    """Explicit resources for the tiny ASGI router under test."""

    app: FastAPI
    client: AsyncClient
    db: AsyncSession
    sessions: async_sessionmaker[AsyncSession]
    reader: StubReader
    legacy: LegacySpy
    factories: list[bool]
    session_entries: list[bool]


@pytest_asyncio.fixture
async def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    """Create only owned user/role tables and inject every route side effect."""
    import app.db.database as database

    def reject_default_engine() -> None:
        raise AssertionError("default database must never be resolved")

    monkeypatch.setattr(database, "_get_engine", reject_default_engine)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reference-control.sqlite'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(
                lambda bind: Base.metadata.create_all(bind, tables=[User.__table__, user_roles])
            )
        async with sessions() as seed:
            await seed.execute(
                insert(User).values(
                    id=_USER_ID,
                    username="fixture-reference",
                    email="fixture-reference@example.test",
                    hashed_password="fixture-unused-hash",
                    is_active=True,
                )
            )
            await seed.execute(insert(user_roles).values(user_id=_USER_ID, role=Role.USER.value))
            await seed.commit()
        async with sessions() as db:
            reader = StubReader(db)
            legacy = LegacySpy()
            factories: list[bool] = []
            session_entries: list[bool] = []

            def make_reader() -> StubReader:
                factories.append(True)
                return reader

            @asynccontextmanager
            async def owned_db() -> AsyncIterator[AsyncSession]:
                session_entries.append(True)
                yield db

            app = FastAPI()
            app.include_router(base.router, prefix="/data")
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(sub=_USER_ID)
            app.dependency_overrides[get_instrument_reference_session_factory] = lambda: owned_db
            app.dependency_overrides[base.get_market_instrument_service] = lambda: legacy
            app.dependency_overrides[get_instrument_reference_catalog] = lambda: (
                InstrumentReferenceCatalog(enabled=True, client_factory=make_reader)
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://fixture.test"
            ) as client:
                yield Harness(app, client, db, sessions, reader, legacy, factories, session_entries)
            assert not db.in_transaction()
    finally:
        await engine.dispose()


async def test_enabled_route_uses_exact_options_and_explicit_alias_date(harness: Harness) -> None:
    response = await harness.client.get(
        _PATH, params={"search": "HIST", "effective_on": "2015-01-01", "limit": 10}
    )
    assert response.status_code == 200
    assert response.json() == json.loads(_FIXTURE.read_text())["options_response"]
    assert harness.reader.calls == [
        {"search": "HIST", "limit": 10, "effective_on": date(2015, 1, 1)}
    ]
    assert harness.factories == [True]
    assert harness.session_entries == [True]
    assert harness.legacy.calls == []


async def test_enabled_route_does_not_invent_an_effective_date(harness: Harness) -> None:
    response = await harness.client.get(_PATH)
    assert response.status_code == 200
    assert harness.reader.calls[0]["effective_on"] is None


@pytest.mark.parametrize("role", [Role.GUEST.value, "unrecognized-role"])
async def test_read_denial_happens_before_client_construction(harness: Harness, role: str) -> None:
    async with harness.sessions() as session:
        await session.execute(delete(user_roles).where(user_roles.c.user_id == _USER_ID))
        await session.execute(insert(user_roles).values(user_id=_USER_ID, role=role))
        await session.commit()
    response = await harness.client.get(_PATH)
    assert response.status_code == 403
    assert response.json() == {
        "detail": {"code": "MARKET_DATA_READ_ENTITLEMENT_DENIED", "catalog_mode": "opendata"}
    }
    assert harness.factories == []
    assert harness.reader.calls == []
    assert harness.legacy.calls == []


@pytest.mark.parametrize("change", ["disable", "remove-read", "change-grants"])
async def test_revocation_during_fetch_discards_result(harness: Harness, change: str) -> None:
    async def revoke() -> None:
        async with harness.sessions() as session:
            if change == "disable":
                await session.execute(
                    update(User).where(User.id == _USER_ID).values(is_active=False)
                )
            else:
                await session.execute(delete(user_roles).where(user_roles.c.user_id == _USER_ID))
                role = Role.GUEST if change == "remove-read" else Role.PREMIUM
                await session.execute(insert(user_roles).values(user_id=_USER_ID, role=role.value))
            await session.commit()

    harness.reader.action = revoke
    response = await harness.client.get(_PATH)
    assert response.status_code == 403
    assert response.json()["detail"]["catalog_mode"] == "opendata"
    assert "items" not in response.json()
    assert harness.legacy.calls == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("OPENDATA_REFERENCE_UNAVAILABLE", 503),
        ("OPENDATA_REFERENCE_PROTOCOL_INVALID", 503),
        ("OPENDATA_REFERENCE_LIMIT_EXCEEDED", 503),
        ("OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED", 422),
        ("OPENDATA_REFERENCE_CONFIG_INVALID", 503),
        ("OPENDATA_REFERENCE_RATE_LIMITED", 429),
    ],
)
async def test_upstream_failures_are_safe_and_never_fall_back(
    harness: Harness, code: str, status: int
) -> None:
    harness.reader.failure = code
    response = await harness.client.get(_PATH)
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code, "catalog_mode": "opendata"}}
    assert harness.legacy.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"effective_on": "20260101"},
        {"effective_on": "2026-02-30"},
        {"effective_on": "2026-01-01T00:00:00"},
        {"effective_on": ""},
        {"limit": "81"},
        {"search": "A" * 129},
        {"search": " 600001"},
        {"search": "600001 "},
        {"search": "600\x00001"},
        {"search": "600\n001"},
    ],
)
async def test_invalid_enabled_input_is_rejected_before_fetch(
    harness: Harness, params: dict[str, str]
) -> None:
    response = await harness.client.get(_PATH, params=params)
    assert response.status_code == 422
    assert response.json() == {
        "detail": {"code": "OPENDATA_REFERENCE_REQUEST_INVALID", "catalog_mode": "opendata"}
    }
    assert harness.factories == []


async def test_missing_factory_fails_closed(harness: Harness) -> None:
    harness.app.dependency_overrides[get_instrument_reference_catalog] = lambda: (
        InstrumentReferenceCatalog(enabled=True)
    )
    response = await harness.client.get(_PATH)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "OPENDATA_REFERENCE_CONFIG_INVALID"
    assert harness.legacy.calls == []


@pytest.mark.parametrize("during_fetch", [False, True])
async def test_control_database_failure_is_safe(harness: Harness, during_fetch: bool) -> None:
    async def lose_control_table() -> None:
        async with harness.sessions() as session:
            await session.execute(text("DROP TABLE users"))
            await session.commit()

    if during_fetch:
        harness.reader.action = lose_control_table
    else:
        await lose_control_table()
    response = await harness.client.get(_PATH)
    assert response.status_code == 503
    assert response.json() == {
        "detail": {"code": "OPENDATA_REFERENCE_UNAVAILABLE", "catalog_mode": "opendata"}
    }
    assert harness.legacy.calls == []


@pytest.mark.parametrize(
    "asset_type", ["stock", "fund", "futures", "bond", "option", "fx", "crypto"]
)
async def test_disabled_catalog_preserves_legacy_signature(
    harness: Harness, asset_type: str
) -> None:
    harness.app.dependency_overrides[get_instrument_reference_catalog] = lambda: (
        InstrumentReferenceCatalog(enabled=False)
    )
    response = await harness.client.get(
        _PATH, params={"asset_type": asset_type, "limit": 200, "effective_on": "ignored"}
    )
    assert response.status_code == 200
    assert harness.legacy.calls == [{"asset_type": asset_type, "search": "", "limit": 200}]
    assert harness.factories == []
    assert harness.session_entries == []


async def test_enabled_switch_does_not_change_other_assets(harness: Harness) -> None:
    response = await harness.client.get(_PATH, params={"asset_type": "fund", "limit": 200})
    assert response.status_code == 200
    assert harness.legacy.calls == [{"asset_type": "fund", "search": "", "limit": 200}]
    assert harness.factories == []
    assert harness.session_entries == []


async def test_authentication_is_required(harness: Harness) -> None:
    del harness.app.dependency_overrides[get_current_user]
    response = await harness.client.get(_PATH)
    assert response.status_code == 401
    assert harness.factories == []


async def test_cancellation_propagates_and_releases_read_transaction(harness: Harness) -> None:
    async def cancel() -> None:
        raise asyncio.CancelledError

    harness.reader.action = cancel
    with pytest.raises(asyncio.CancelledError):
        await harness.client.get(_PATH)
    assert harness.legacy.calls == []
    assert not harness.db.in_transaction()


async def test_configuration_is_default_off_and_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    defaults = Settings(_env_file=None, DEBUG=True)
    assert defaults.MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED is False
    assert defaults.MARKET_DATA_OPENDATA_INSTRUMENT_DATASET_ID == ""
    assert defaults.MARKET_DATA_OPENDATA_INSTRUMENT_SOURCE_ID == ""
    assert defaults.MARKET_DATA_OPENDATA_INSTRUMENT_CONTRACT_SHA256 == ""

    def reject_environment(**kwargs: Any) -> None:
        raise AssertionError("disabled/unqueried catalog must not read credentials")

    from app.api.data import instrument_reference

    monkeypatch.setattr(
        instrument_reference.OpendataCredentials, "from_environment", reject_environment
    )
    assert not build_instrument_reference_catalog(defaults).enabled
    enabled = SimpleNamespace(MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED=True)
    assert build_instrument_reference_catalog(enabled).enabled


@pytest.mark.parametrize(
    "environment", [{}, {"OPENDATA_API_KEY": "fixture-key", "OPENDATA_BASE_URL": "invalid"}]
)
async def test_missing_credentials_are_fixed_errors(environment: dict[str, str]) -> None:
    settings = SimpleNamespace(MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED=True)
    catalog = build_instrument_reference_catalog(settings, environment=environment)
    assert catalog.client_factory is not None
    with pytest.raises(InstrumentReferenceError) as error:
        catalog.client_factory()
    assert error.value.code == "OPENDATA_REFERENCE_CONFIG_INVALID"


async def test_factory_uses_only_exact_server_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.data import instrument_reference

    captured: list[object] = []
    sentinel = object()

    def make_client(config: object) -> object:
        captured.append(config)
        return sentinel

    monkeypatch.setattr(instrument_reference, "InstrumentReferenceClient", make_client)
    settings = SimpleNamespace(
        MARKET_DATA_OPENDATA_INSTRUMENT_CATALOG_ENABLED=True,
        MARKET_DATA_OPENDATA_INSTRUMENT_DATASET_ID="fixture.instrument-reference.stock",
        MARKET_DATA_OPENDATA_INSTRUMENT_SOURCE_ID="fixture.reference",
        MARKET_DATA_OPENDATA_INSTRUMENT_CONTRACT_SHA256="8dc2e5912f5a8c9e371beed3c36c772fe32914f59065d7655310a4e6e3be5c96",
    )
    catalog = build_instrument_reference_catalog(
        settings,
        environment={
            "OPENDATA_API_KEY": "fixture-only-key",
            "OPENDATA_BASE_URL": "https://reference.example.test",
        },
    )
    assert captured == []
    assert catalog.client_factory is not None
    assert catalog.client_factory() is sentinel
    assert len(captured) == 1
    config = captured[0]
    assert config.dataset_id == settings.MARKET_DATA_OPENDATA_INSTRUMENT_DATASET_ID
    assert config.source_id == settings.MARKET_DATA_OPENDATA_INSTRUMENT_SOURCE_ID
    assert config.contract_sha256 == settings.MARKET_DATA_OPENDATA_INSTRUMENT_CONTRACT_SHA256
    assert config.base_url == "https://reference.example.test"
    assert config.api_key == "fixture-only-key"
    assert "fixture-only-key" not in repr(config)
