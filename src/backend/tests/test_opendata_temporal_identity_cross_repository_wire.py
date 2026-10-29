"""Opt-in synthetic AFI-to-OpenData temporal-identity wire contract test.

The test sends the already-shipped AFI client through the real OpenData
``identity.resolve`` ASGI router. It uses only a private temporary SQLite file,
synthetic API keys, a synthetic grant, and an explicitly constructed pin. The
ASGI transport has no socket and accepts only the one identity route, so this
test cannot reach a production service or a market-data provider.

Run with ``AFI_OPENDATA_IDENTITY_WIRE_TEST=1`` and ``OPENDATA_REPO`` set to the
OpenData checkout root. Keep ``--noconftest`` for the isolated acceptance run.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import AsyncGenerator
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AFI_OPENDATA_IDENTITY_WIRE_TEST") != "1",
    reason="set AFI_OPENDATA_IDENTITY_WIRE_TEST=1 for the isolated OpenData ASGI contract test",
)

_DATASET_ID = "instrument.identity"
_SOURCE_ID = "akshare"
_AUTHORITY_ID = "reviewed-market-authority"
_REGISTRY_ID = "synthetic-a-share-registry"
_REFERENCE_VERSION = "wire-fixture-v1"
_START = date(2020, 1, 1)
_END = date(2020, 1, 5)
_ASGI_ORIGIN = "http://127.0.0.1:48123"
_PATH = "/api/v2/identity/resolve"
_PRESERVED_ENVIRONMENT = frozenset(
    {"PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR"}
)


@dataclass(frozen=True, slots=True)
class _SyntheticKeys:
    """Per-test API keys; repr must never reveal plaintext credentials."""

    allowed: str = field(repr=False)
    missing_operation: str = field(repr=False)
    missing_domain: str = field(repr=False)


@dataclass(slots=True)
class _CountingSnapshotStore:
    """Observe store access while delegating to the real SQLite snapshot store."""

    store: Any = field(repr=False)
    calls: int = 0

    def get(
        self,
        *,
        authority_id: str,
        registry_id: str,
        reference_version: str,
        expected_sha256: str,
    ) -> Any:
        """Count and forward the exact immutable snapshot lookup."""
        self.calls += 1
        return self.store.get(
            authority_id=authority_id,
            registry_id=registry_id,
            reference_version=reference_version,
            expected_sha256=expected_sha256,
        )


class _IdentityRouteOnlyASGITransport(httpx.AsyncBaseTransport):
    """Route requests directly into ASGI and reject every other destination."""

    def __init__(self, app: Any) -> None:
        self._transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        self.requests: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Allow only the exact synthetic OpenData identity endpoint."""
        url = request.url
        if (
            request.method != "POST"
            or url.scheme != "http"
            or url.host != "127.0.0.1"
            or url.port != 48123
            or url.path != _PATH
            or url.query
            or url.userinfo
        ):
            raise httpx.ConnectError("identity wire fixture accepts only its ASGI route")
        self.requests.append((request.method, url.path))
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        """Keep the ASGI transport owned by the test fixture."""
        return None


@dataclass(slots=True)
class _OpenDataFixture:
    """Private ASGI app, temp engines, test keys, and the exact trusted pin."""

    app: Any
    transport: _IdentityRouteOnlyASGITransport
    pin: Any
    keys: _SyntheticKeys
    store: _CountingSnapshotStore
    afi_credentials_class: Any = field(repr=False)
    afi_client_class: Any = field(repr=False)
    afi_config_class: Any = field(repr=False)
    afi_error_class: Any = field(repr=False)
    afi_pin_class: Any = field(repr=False)
    snapshot_engine: Any = field(repr=False)
    auth_engine: Any = field(repr=False)


@dataclass(slots=True)
class _OpenDataImportState:
    """Track target-checkout imports so setup failures can clean them safely."""

    repository_path: str
    package_root: Path
    preexisting_modules: frozenset[str]
    afi_package_root: Path
    preexisting_afi_modules: frozenset[str]
    repository_path_was_added: bool = False


def _is_within(path: Path, root: Path) -> bool:
    """Return whether a resolved path is contained by the fixed checkout root."""
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _validate_package_module_cache(package_name: str, package_root: Path) -> None:
    """Reject cached package modules or search paths outside the fixed checkout."""
    import sys

    root = package_root.resolve()
    prefix = f"{package_name}."
    for name, module in tuple(sys.modules.items()):
        if name != package_name and not name.startswith(prefix):
            continue
        paths: list[Path] = []
        origin = getattr(module, "__file__", None)
        if isinstance(origin, str):
            paths.append(Path(origin))
        specification = getattr(module, "__spec__", None)
        spec_origin = getattr(specification, "origin", None)
        if isinstance(spec_origin, str) and spec_origin not in {"built-in", "frozen"}:
            paths.append(Path(spec_origin))
        for search_path in getattr(module, "__path__", ()) or ():
            if isinstance(search_path, str):
                paths.append(Path(search_path))
        if not paths or any(not _is_within(path, root) for path in paths):
            raise RuntimeError(
                f"cached {package_name} modules do not come exclusively from the selected checkout"
            )


def _cleanup_opendata_imports(state: _OpenDataImportState) -> None:
    """Reset test-local limiter state and undo only imports/path changes made here."""
    import sys

    try:
        rate_limit_module = sys.modules.get("opendata.core.api_key_rate_limit")
        rate_limiter = getattr(rate_limit_module, "api_key_rate_limiter", None)
        if rate_limiter is not None:
            rate_limiter.reset_local_state()
    finally:
        for name in tuple(sys.modules):
            if name == "opendata" or name.startswith("opendata."):
                if name not in state.preexisting_modules:
                    del sys.modules[name]
            elif name == "app" or name.startswith("app."):
                if name not in state.preexisting_afi_modules:
                    del sys.modules[name]
        if state.repository_path_was_added:
            try:
                sys.path.remove(state.repository_path)
            except ValueError:
                pass


def _dispose_async_engine(engine: Any) -> None:
    """Dispose an async engine from this synchronous pytest fixture's cleanup stack."""
    asyncio.run(engine.dispose())


def _configure_isolated_settings(monkeypatch: pytest.MonkeyPatch, state_dir: Path) -> None:
    """Force settings, HOME, and local service configuration into the private test directory."""
    monkeypatch.chdir(state_dir)
    if (state_dir / ".env").exists():
        raise RuntimeError("isolated OpenData settings directory must not contain .env")
    for name in tuple(os.environ):
        if name not in _PRESERVED_ENVIRONMENT:
            monkeypatch.delenv(name, raising=False)
    environment = {
        "APP_ENV": "testing",
        "TESTING": "true",
        "PYTHON_DOTENV_DISABLED": "1",
        "REDIS_URL": "",
        "SENTRY_DSN": "",
        "ENABLE_SCHEDULER": "false",
        "SCHEDULER_BOOTSTRAP_ON_STARTUP": "false",
        "PATROL_ENABLED": "false",
        "MYSQL_HOST": "fixture-db-disabled.invalid",
        "MYSQL_PORT": "1",
        "MYSQL_USER": "fixture_disabled",
        "MYSQL_PASSWORD": "",
        "MYSQL_DATABASE": "fixture_disabled",
        "DATA_MYSQL_HOST": "fixture-db-disabled.invalid",
        "DATA_MYSQL_PORT": "1",
        "DATA_MYSQL_USER": "fixture_disabled",
        "DATA_MYSQL_PASSWORD": "",
        "DATA_MYSQL_DATABASE": "fixture_disabled",
        "API_KEY_PEPPER": secrets.token_urlsafe(32),
        "API_KEY_FAILURE_DELAY_SECONDS": "0",
        "RATE_LIMIT_PER_MINUTE": "1000",
        "CACHE_DIR": str(state_dir / "cache"),
        "XDG_CACHE_HOME": str(state_dir / "cache"),
        "DATABASE_URL": "sqlite+aiosqlite://",
        "DEBUG": "true",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "JWT_SECRET_KEY": secrets.token_urlsafe(48),
        "SQL_ECHO": "false",
        "MARKET_DATA_QUERY_V2_ENABLED": "false",
        "MARKET_DATA_ONLINE_FETCH_ENABLED": "false",
        "MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED": "false",
        "MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED": "false",
        "HOME": str(state_dir),
        "USER": "afi-wire-test",
        "LOGNAME": "afi-wire-test",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    expected_home = state_dir.resolve()
    configured_home = os.environ.get("HOME")
    if (
        configured_home is None
        or Path(configured_home).resolve() != expected_home
        or Path.home().resolve() != expected_home
    ):
        raise RuntimeError("isolated HOME must resolve to the private temporary test directory")
    if os.environ.get("USER") != "afi-wire-test" or os.environ.get("LOGNAME") != ("afi-wire-test"):
        raise RuntimeError("isolated user identity must use fixed synthetic values")


def _open_opendata_modules(
    repository: Path,
    import_state: _OpenDataImportState,
) -> dict[str, Any]:
    """Import the actual OpenData route and domain modules from the chosen checkout."""
    import sys

    expected_route = repository / "opendata" / "api" / "temporal_identity.py"
    if not expected_route.is_file() or not _is_within(
        expected_route,
        import_state.package_root,
    ):
        raise RuntimeError("OPENDATA_REPO does not contain the temporal identity API")
    _validate_package_module_cache("opendata", import_state.package_root)
    repository_text = str(repository)
    repository_path_was_added = repository_text not in sys.path
    if repository_path_was_added:
        sys.path.insert(0, repository_text)
        import_state.repository_path_was_added = True

    from fastapi import FastAPI
    from opendata.api.published_access import DatasetGrant, DatasetGrantRegistry
    from opendata.api.published_data import get_dataset_grants
    from opendata.api.temporal_identity import router
    from opendata.core.api_key_rate_limit import api_key_rate_limiter
    from opendata.core.database import Base, get_db
    from opendata.data.temporal_identity_pins import TemporalIdentityPin as ServerPin
    from opendata.data.temporal_identity_pins import TemporalIdentityPinRegistry
    from opendata.data.temporal_identity_store import TemporalIdentitySnapshotStore
    from opendata.data.temporal_instrument_identity import (
        TemporalIdentityAssignment,
        TemporalIdentityRegistry,
    )
    from opendata.data.temporal_instrument_identity_snapshot import (
        encode_temporal_identity_snapshot,
    )
    from opendata.models.api_key import ApiKey, ApiKeyStatus
    from opendata.models.user import User, UserRole
    from opendata.services.api_key_service import generate_key, hash_key
    from sqlalchemy import create_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session

    _validate_package_module_cache("opendata", import_state.package_root)
    return {
        "FastAPI": FastAPI,
        "create_engine": create_engine,
        "async_sessionmaker": async_sessionmaker,
        "create_async_engine": create_async_engine,
        "Session": Session,
        "DatasetGrant": DatasetGrant,
        "DatasetGrantRegistry": DatasetGrantRegistry,
        "get_dataset_grants": get_dataset_grants,
        "router": router,
        "api_key_rate_limiter": api_key_rate_limiter,
        "Base": Base,
        "get_db": get_db,
        "ServerPin": ServerPin,
        "TemporalIdentityPinRegistry": TemporalIdentityPinRegistry,
        "encode_temporal_identity_snapshot": encode_temporal_identity_snapshot,
        "TemporalIdentitySnapshotStore": TemporalIdentitySnapshotStore,
        "TemporalIdentityAssignment": TemporalIdentityAssignment,
        "TemporalIdentityRegistry": TemporalIdentityRegistry,
        "ApiKey": ApiKey,
        "ApiKeyStatus": ApiKeyStatus,
        "User": User,
        "UserRole": UserRole,
        "generate_key": generate_key,
        "hash_key": hash_key,
    }


def _open_afi_client_modules(import_state: _OpenDataImportState) -> dict[str, Any]:
    """Import the shipped AFI client only after temporary settings are active."""
    _validate_package_module_cache("app", import_state.afi_package_root)
    from app.services.market_data.opendata_credentials import OpendataCredentials
    from app.services.market_data.opendata_temporal_identity import (
        OpendataTemporalIdentityClient,
        OpendataTemporalIdentityConfig,
        OpendataTemporalIdentityError,
        OpendataTemporalIdentityPin,
    )

    _validate_package_module_cache("app", import_state.afi_package_root)
    return {
        "OpendataCredentials": OpendataCredentials,
        "OpendataTemporalIdentityClient": OpendataTemporalIdentityClient,
        "OpendataTemporalIdentityConfig": OpendataTemporalIdentityConfig,
        "OpendataTemporalIdentityError": OpendataTemporalIdentityError,
        "OpendataTemporalIdentityPin": OpendataTemporalIdentityPin,
    }


def _create_0021_schema(engine: Any, repository: Path) -> None:
    """Apply the checked-in warehouse migration to this test-owned SQLite file."""
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    migration_path = next(
        (repository / "alembic_data" / "versions").glob("20261029-0021_*.py"),
        None,
    )
    if migration_path is None or not _is_within(migration_path, repository):
        raise RuntimeError("OpenData warehouse migration 0021 is unavailable")
    specification = importlib.util.spec_from_file_location(
        "_afi_test_opendata_temporal_identity_migration_0021",
        migration_path,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("OpenData warehouse migration 0021 cannot be loaded")
    migration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version_data (version_num VARCHAR(64) NOT NULL PRIMARY KEY)"
        )
        connection.execute(
            text("INSERT INTO alembic_version_data (version_num) VALUES (:version)"),
            {"version": "0020_run_ledger_claim_policy"},
        )
        context = MigrationContext.configure(
            connection,
            opts={"version_table": "alembic_version_data"},
        )
        with Operations.context(context):
            migration.upgrade()


def _build_fixture(
    *,
    repository: Path,
    state_dir: Path,
    resources: ExitStack,
    import_state: _OpenDataImportState,
) -> _OpenDataFixture:
    """Seed exact temporary auth/snapshot stores and mount the real route."""
    afi_modules = _open_afi_client_modules(import_state)
    modules = _open_opendata_modules(repository, import_state)
    create_engine = modules["create_engine"]
    create_async_engine = modules["create_async_engine"]
    async_sessionmaker = modules["async_sessionmaker"]
    Session = modules["Session"]
    Base = modules["Base"]
    User = modules["User"]
    UserRole = modules["UserRole"]
    ApiKey = modules["ApiKey"]
    ApiKeyStatus = modules["ApiKeyStatus"]
    generate_key = modules["generate_key"]
    hash_key = modules["hash_key"]
    TemporalIdentityAssignment = modules["TemporalIdentityAssignment"]
    TemporalIdentityRegistry = modules["TemporalIdentityRegistry"]
    encode_snapshot = modules["encode_temporal_identity_snapshot"]
    TemporalIdentitySnapshotStore = modules["TemporalIdentitySnapshotStore"]
    ServerPin = modules["ServerPin"]
    TemporalIdentityPinRegistry = modules["TemporalIdentityPinRegistry"]
    DatasetGrant = modules["DatasetGrant"]
    DatasetGrantRegistry = modules["DatasetGrantRegistry"]
    FastAPI = modules["FastAPI"]

    auth_path = state_dir / "auth.sqlite"
    snapshot_path = state_dir / "warehouse.sqlite"
    sync_auth_engine = create_engine(f"sqlite:///{auth_path}")
    resources.callback(sync_auth_engine.dispose)
    Base.metadata.create_all(sync_auth_engine, tables=[User.__table__, ApiKey.__table__])
    keys = _SyntheticKeys(
        allowed=generate_key(),
        missing_operation=generate_key(),
        missing_domain=generate_key(),
    )
    key_scopes = {
        keys.allowed: ["equity", "identity.resolve"],
        keys.missing_operation: ["equity"],
        keys.missing_domain: ["identity.resolve"],
    }
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    with Session(sync_auth_engine) as session:
        user = User(
            username="temporal-identity-wire",
            email="temporal-identity-wire@example.test",
            hashed_password="synthetic-test-only",
            role=UserRole.USER,
            is_active=True,
        )
        session.add(user)
        session.flush()
        for index, (plaintext, scopes) in enumerate(key_scopes.items(), start=1):
            session.add(
                ApiKey(
                    key_hash=hash_key(plaintext),
                    name=f"synthetic identity key {index}",
                    owner_user_id=user.id,
                    scopes=scopes,
                    rate_limit=1000,
                    status=ApiKeyStatus.ACTIVE,
                    expires_at=expires_at,
                )
            )
        session.commit()

    auth_engine = create_async_engine(f"sqlite+aiosqlite:///{auth_path}")
    resources.callback(_dispose_async_engine, auth_engine)
    auth_sessions = async_sessionmaker(auth_engine, expire_on_commit=False)
    snapshot_engine = create_engine(f"sqlite:///{snapshot_path}")
    resources.callback(snapshot_engine.dispose)
    _create_0021_schema(snapshot_engine, repository)
    registry = TemporalIdentityRegistry(
        reference_version=_REFERENCE_VERSION,
        evidence_ref="docs/evidence/identity/synthetic-wire-fixture.json",
        assignments=(
            TemporalIdentityAssignment(
                assignment_id="wire-assignment-600000",
                instrument_id="synthetic-instrument-600000",
                exchange="XSHG",
                symbol="600000",
                valid_from=date(2020, 1, 2),
                valid_to=date(2020, 1, 4),
                source_id=_SOURCE_ID,
                source_version="synthetic-source-v1",
                evidence_ref="docs/evidence/identity/synthetic-assignment.json",
                source_sha256="b" * 64,
            ),
        ),
    )
    snapshot_store = TemporalIdentitySnapshotStore(snapshot_engine)
    snapshot_bytes = encode_snapshot(registry)
    import hashlib

    digest = hashlib.sha256(snapshot_bytes).hexdigest()
    snapshot_store.put(
        authority_id=_AUTHORITY_ID,
        registry_id=_REGISTRY_ID,
        registry=registry,
        expected_sha256=digest,
    )
    trusted_pin = ServerPin(
        dataset_id=_DATASET_ID,
        source_id=_SOURCE_ID,
        authority_id=_AUTHORITY_ID,
        registry_id=_REGISTRY_ID,
        reference_version=_REFERENCE_VERSION,
        snapshot_sha256=digest,
    )
    pin_registry = TemporalIdentityPinRegistry((trusted_pin,))
    grants = DatasetGrantRegistry(
        (
            DatasetGrant(
                dataset_id=_DATASET_ID,
                domain="equity",
                source_id=_SOURCE_ID,
                permitted_operations=("identity.resolve",),
                purposes=("research",),
                valid_from=datetime(2000, 1, 1, tzinfo=timezone.utc),
                valid_until=datetime(2100, 1, 1, tzinfo=timezone.utc),
                review_evidence="TST-204-WIRE",
            ),
        )
    )

    async def fixture_get_db() -> AsyncGenerator[Any, None]:
        """Yield a session against only the private temporary auth database."""
        async with auth_sessions() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(modules["router"])
    app.dependency_overrides[modules["get_db"]] = fixture_get_db
    app.dependency_overrides[modules["get_dataset_grants"]] = lambda: grants
    app.state.temporal_identity_pin_registry = pin_registry
    counting_store = _CountingSnapshotStore(snapshot_store)
    app.state.temporal_identity_snapshot_store = counting_store
    transport = _IdentityRouteOnlyASGITransport(app)
    pin = afi_modules["OpendataTemporalIdentityPin"](
        dataset_id=_DATASET_ID,
        source_id=_SOURCE_ID,
        authority_id=_AUTHORITY_ID,
        registry_id=_REGISTRY_ID,
        reference_version=_REFERENCE_VERSION,
        snapshot_sha256=digest,
    )
    return _OpenDataFixture(
        app=app,
        transport=transport,
        pin=pin,
        keys=keys,
        store=counting_store,
        afi_credentials_class=afi_modules["OpendataCredentials"],
        afi_client_class=afi_modules["OpendataTemporalIdentityClient"],
        afi_config_class=afi_modules["OpendataTemporalIdentityConfig"],
        afi_error_class=afi_modules["OpendataTemporalIdentityError"],
        afi_pin_class=afi_modules["OpendataTemporalIdentityPin"],
        snapshot_engine=snapshot_engine,
        auth_engine=auth_engine,
    )


@pytest.fixture
def opendata_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Create and dispose private SQLite state for the actual OpenData router."""
    repository_value = os.environ.get("OPENDATA_REPO")
    if not repository_value:
        pytest.fail("OPENDATA_REPO is required for the isolated cross-repository contract test")
    repository = Path(repository_value).resolve()
    if not repository.is_absolute():
        pytest.fail("OPENDATA_REPO must identify the OpenData checkout root")
    import sys

    preexisting_opendata_modules = frozenset(
        name for name in sys.modules if name == "opendata" or name.startswith("opendata.")
    )
    preexisting_afi_modules = frozenset(
        name for name in sys.modules if name == "app" or name.startswith("app.")
    )
    import_state = _OpenDataImportState(
        repository_path=str(repository),
        package_root=repository / "opendata",
        preexisting_modules=preexisting_opendata_modules,
        afi_package_root=Path(__file__).resolve().parents[1] / "app",
        preexisting_afi_modules=preexisting_afi_modules,
    )
    state_dir = tmp_path / "opendata-identity-wire"
    state_dir.mkdir(mode=0o700)
    state_dir.chmod(0o700)
    with ExitStack() as resources:
        resources.callback(_cleanup_opendata_imports, import_state)
        _configure_isolated_settings(monkeypatch, state_dir)
        fixture = _build_fixture(
            repository=repository,
            state_dir=state_dir,
            resources=resources,
            import_state=import_state,
        )
        yield fixture


def _client(
    fixture: _OpenDataFixture,
    api_key: str,
    *,
    pin: Any | None = None,
) -> Any:
    """Build the shipped AFI client with an ASGI-only, single-route transport."""
    credentials = fixture.afi_credentials_class(api_key, base_url=_ASGI_ORIGIN)
    config = fixture.afi_config_class(credentials=credentials, pin=pin or fixture.pin)
    return fixture.afi_client_class(config, transport=fixture.transport)


def test_afi_client_uses_real_route_and_preserves_known_and_unknown_segments(
    opendata_fixture: _OpenDataFixture,
) -> None:
    """Resolve from migration-backed snapshot bytes through real auth and route code."""

    async def scenario() -> None:
        client = _client(opendata_fixture, opendata_fixture.keys.allowed)
        known_query = await client.resolve_pair(
            exchange="XSHG",
            symbol="600000",
            window_start=_START,
            window_end_exclusive=_END,
        )
        assert known_query.snapshot_sha256 == opendata_fixture.pin.snapshot_sha256
        assert [item.status for item in known_query.segments] == ["unknown", "known", "unknown"]
        assert known_query.segments[0].start == date(2020, 1, 1)
        assert known_query.segments[0].end_exclusive == date(2020, 1, 2)
        assert known_query.segments[1].instrument_id == "synthetic-instrument-600000"
        assert known_query.segments[1].source_id == _SOURCE_ID
        assert known_query.segments[2].start == date(2020, 1, 4)
        assert known_query.segments[2].end_exclusive == _END
        assert known_query.completeness == "not_established_by_identity_resolution"
        assert (
            known_query.source_integrity
            == "snapshot_bytes_pinned_source_evidence_not_authenticated"
        )

        unknown_query = await client.resolve_pair(
            exchange="XSHG",
            symbol="600999",
            window_start=_START,
            window_end_exclusive=_END,
        )
        assert len(unknown_query.segments) == 1
        assert unknown_query.segments[0].status == "unknown"
        assert unknown_query.segments[0].start == _START
        assert unknown_query.segments[0].end_exclusive == _END
        assert unknown_query.segments[0].instrument_id is None
        assert opendata_fixture.store.calls == 2
        assert opendata_fixture.transport.requests == [
            ("POST", _PATH),
            ("POST", _PATH),
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "key_name",
    ["missing_operation", "missing_domain"],
)
def test_scope_denials_happen_before_snapshot_read(
    opendata_fixture: _OpenDataFixture,
    key_name: str,
) -> None:
    """Require both the operation and the grant's domain in the real API key."""

    async def scenario() -> None:
        key = getattr(opendata_fixture.keys, key_name)
        client = _client(opendata_fixture, key)
        with pytest.raises(opendata_fixture.afi_error_class) as raised:
            await client.resolve_pair(
                exchange="XSHG",
                symbol="600000",
                window_start=_START,
                window_end_exclusive=_END,
            )
        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_UNAVAILABLE"
        assert opendata_fixture.store.calls == 0
        assert opendata_fixture.transport.requests == [("POST", _PATH)]
        assert key not in str(raised.value)

    asyncio.run(scenario())


def test_pin_or_dataset_grant_mismatch_fails_closed_before_snapshot_read(
    opendata_fixture: _OpenDataFixture,
) -> None:
    """Reject a caller-selected digest and an ungranted dataset without lookup."""

    async def scenario() -> None:
        mismatched_pin = opendata_fixture.afi_pin_class(
            dataset_id=_DATASET_ID,
            source_id=_SOURCE_ID,
            authority_id=_AUTHORITY_ID,
            registry_id=_REGISTRY_ID,
            reference_version=_REFERENCE_VERSION,
            snapshot_sha256="c" * 64,
        )
        client = _client(
            opendata_fixture,
            opendata_fixture.keys.allowed,
            pin=mismatched_pin,
        )
        with pytest.raises(opendata_fixture.afi_error_class) as raised_pin:
            await client.resolve_pair(
                exchange="XSHG",
                symbol="600000",
                window_start=_START,
                window_end_exclusive=_END,
            )
        assert raised_pin.value.code == "OPENDATA_TEMPORAL_IDENTITY_UNAVAILABLE"
        assert opendata_fixture.store.calls == 0

        ungranted_pin = opendata_fixture.afi_pin_class(
            dataset_id="ungranted.identity",
            source_id=_SOURCE_ID,
            authority_id=_AUTHORITY_ID,
            registry_id=_REGISTRY_ID,
            reference_version=_REFERENCE_VERSION,
            snapshot_sha256=opendata_fixture.pin.snapshot_sha256,
        )
        ungranted_client = _client(
            opendata_fixture,
            opendata_fixture.keys.allowed,
            pin=ungranted_pin,
        )
        with pytest.raises(opendata_fixture.afi_error_class) as raised_grant:
            await ungranted_client.resolve_pair(
                exchange="XSHG",
                symbol="600000",
                window_start=_START,
                window_end_exclusive=_END,
            )
        assert raised_grant.value.code == "OPENDATA_TEMPORAL_IDENTITY_UNAVAILABLE"
        assert opendata_fixture.store.calls == 0
        assert opendata_fixture.transport.requests == [("POST", _PATH), ("POST", _PATH)]

    asyncio.run(scenario())


def test_unavailable_route_raises_instead_of_returning_local_fallback(
    opendata_fixture: _OpenDataFixture,
) -> None:
    """An absent server store propagates failure; the client has no local fallback."""

    async def scenario() -> None:
        opendata_fixture.app.state.temporal_identity_snapshot_store = None
        client = _client(opendata_fixture, opendata_fixture.keys.allowed)
        with pytest.raises(opendata_fixture.afi_error_class) as raised:
            await client.resolve_pair(
                exchange="XSHG",
                symbol="600000",
                window_start=_START,
                window_end_exclusive=_END,
            )
        assert raised.value.code == "OPENDATA_TEMPORAL_IDENTITY_UNAVAILABLE"
        assert opendata_fixture.store.calls == 0
        assert opendata_fixture.transport.requests == [("POST", _PATH)]

    asyncio.run(scenario())
