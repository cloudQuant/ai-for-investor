# ruff: noqa: E402
"""Run an opt-in, disposable THS acceptance probe for Iteration 198.

The command is deliberately a narrow non-production harness.  It does not use
``DATABASE_URL``, does not alter application configuration or credentials, and
never talks to THS unless ``--live`` is supplied.  A live run creates a fresh
SQLite file, seeds the synthetic control-plane prerequisites (bootstrap +
``dg_providers`` ``ths`` row + ``asset_data_source_registry`` ``ths`` row + a
disposable identity + calendar), exercises the real ``MarketDataQueryService``
and THS adapter through the ``ths-stock-primary-v1`` A-share primary route,
commits that isolated receipt, then verifies an independent ``local_only``
re-read before deleting the file.

Run from ``src/backend`` with the repository-required Conda interpreter:

    /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base \
        python scripts/acceptance/iteration198_ths.py

The default output is a safe ``NOT_RUN`` result and makes no network or
database call.  A live confirmation is explicit:

    /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base \
        python scripts/acceptance/iteration198_ths.py --live

``--database-path`` is optional for operators that need to choose the temporary
file location.  It must name a non-existent ``.db``, ``.sqlite`` or ``.sqlite3``
file under an existing, non-symlink directory.  The harness owns and deletes
that file on every terminal path; it never accepts a database URL or an
existing application database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Permit direct ``python scripts/...`` execution without relying on a caller's
# PYTHONPATH.  This script intentionally does not import the process-global
# database session factory, so an application's configured database can never
# become this harness's target.
BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: F401  # Register all mapped tables before create_all.
from app.db.database import Base
from app.models.asset_research import AssetDataSourceRegistry
from app.models.data_governance import DgProvider
from app.models.market_data_platform import MdObservationRevision, MdSourceSnapshot
from app.models.permission import Role, user_roles
from app.models.user import User
from app.schemas.asset_research import InstrumentIdentity
from app.schemas.market_data_platform import MarketDataQueryRequest
from app.services.market_data.access import MarketDataAccessAuthorizer, MarketDataQueryAccess
from app.services.market_data.bootstrap import (
    CanonicalStorageSpec,
    MarketDataBootstrapSpec,
    MarketDataPlatformBootstrapper,
)
from app.services.market_data.calendar_importer import MANIFEST_VERSION, MarketDataCalendarImporter
from app.services.market_data.catalog import DataCatalogResolver
from app.services.market_data.identity import MarketDataIdentityResolver
from app.services.market_data.master_data import MarketDataIdentityWriter
from app.services.market_data.providers import MarketDataProviderRequest, ProviderFetchResult
from app.services.market_data.query_resolution import MarketDataQueryResolver
from app.services.market_data.query_service import MarketDataQueryExecution, MarketDataQueryService
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
    MarketDataSourcePolicyRegistry,
)
from app.services.market_data.store import MarketDataStore
from app.services.market_data.ths_provider import ThsProvider

UTC = timezone.utc
FAMILY_CONTRACT_VERSION = "market-data-family-v1"
DEFAULT_TRADING_DATE = date(2026, 9, 1)
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_SAFE_WARNING_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})

# THS A-share primary route probe.
FAMILY_ID = "stock.realtime"
ROUTE_ID = "ths-stock-primary-v1"
SOURCE_POLICY_ID = "market-default-v1"
PROVIDER_ID = "ths"
DATASET_CODE = "market.bars"
DATA_KIND = "bars"
REQUIRED_FIELDS = ("close",)
CANONICAL_ID = "instrument:stock:CN-SSE:600519"
DISPLAY_SYMBOL = "600519.SH"
VENUE = "CN-SSE"
REQUEST_ADJUSTMENT = "qfq"


class _Provider(Protocol):
    async def fetch(self, request: MarketDataProviderRequest) -> ProviderFetchResult:
        """Fetch an exact provider request."""


class HarnessError(RuntimeError):
    def __init__(self, code: str, *, stage: str) -> None:
        self.code = code if _SAFE_CODE.fullmatch(code) else "THS_ACCEPTANCE_HARNESS_FAILED"
        self.stage = stage
        super().__init__(self.code)


@dataclass(slots=True)
class _DatabaseTarget:
    path: Path
    kind: str
    _device: int
    _inode: int

    @classmethod
    def allocate(cls, requested_path: str | None) -> _DatabaseTarget:
        if requested_path is None:
            directory = Path(tempfile.mkdtemp(prefix="iteration198-ths-"))
            path = directory / "market_data.sqlite3"
            kind = "temporary"
        else:
            path = _validate_requested_database_path(requested_path)
            kind = "caller_designated_temporary"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise HarnessError("HARNESS_DATABASE_NOT_FRESH", stage="database_target") from exc
        except OSError as exc:
            raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target") from exc
        else:
            os.close(descriptor)
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
        return cls(path=path, kind=kind, _device=metadata.st_dev, _inode=metadata.st_ino)

    def cleanup(self) -> bool:
        removed = True
        try:
            metadata = self.path.lstat()
            if (
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_dev == self._device
                and metadata.st_ino == self._inode
            ):
                self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            removed = False
        for suffix in ("-journal", "-shm", "-wal"):
            try:
                sidecar = Path(f"{self.path}{suffix}")
                if stat.S_ISREG(sidecar.lstat().st_mode):
                    sidecar.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                removed = False
        if self.kind == "temporary":
            try:
                self.path.parent.rmdir()
            except (FileNotFoundError, OSError):
                pass
        return removed


class _RecordingProvider:
    def __init__(self, delegate: _Provider) -> None:
        self._delegate = delegate
        self.attempt_count = 0
        self.observation_count = 0

    async def fetch(self, request: MarketDataProviderRequest) -> ProviderFetchResult:
        self.attempt_count += 1
        result = await self._delegate.fetch(request)
        if isinstance(result, ProviderFetchResult):
            self.observation_count += len(result.observations)
        return result


class _UnexpectedProvider:
    async def fetch(self, request: MarketDataProviderRequest) -> ProviderFetchResult:
        del request
        raise HarnessError("THS_LOCAL_ONLY_PROVIDER_CALLED", stage="local_only_reread")


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="offline emits NOT_RUN; live performs one real THS fetch through the local-first service.",
    )
    parser.add_argument(
        "--database-path",
        metavar="PATH",
        help="A new SQLite .db/.sqlite/.sqlite3 file to create and delete.",
    )
    parser.add_argument(
        "--trading-date",
        metavar="YYYY-MM-DD",
        default=DEFAULT_TRADING_DATE.isoformat(),
        help="One Monday-Friday historical date for the exact single-day probe window.",
    )
    return parser.parse_args(argv)


def _validate_requested_database_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "://" in value:
        raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    raw_path = Path(value).expanduser()
    if not raw_path.is_absolute():
        raw_path = Path.cwd() / raw_path
    if raw_path.name in {"", ".", ".."} or raw_path.suffix.lower() not in _DATABASE_SUFFIXES:
        raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    current = Path(raw_path.anchor)
    for component in raw_path.parts[1:-1]:
        current = current / component
        if current.is_symlink():
            raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    if raw_path.is_symlink() or raw_path.exists():
        raise HarnessError("HARNESS_DATABASE_NOT_FRESH", stage="database_target")
    parent = raw_path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    return raw_path


def _parse_trading_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HarnessError("HARNESS_TRADING_DATE_INVALID", stage="arguments") from exc
    if parsed.weekday() >= 5:
        raise HarnessError("HARNESS_TRADING_DATE_NOT_WEEKDAY", stage="arguments")
    return parsed


def _database_url(path: Path) -> str:
    return str(URL.create(drivername="sqlite+aiosqlite", database=str(path)))


def _window_for(trading_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(trading_date, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _request_for(*, start: datetime, end: datetime, mode: str) -> MarketDataQueryRequest:
    payload: dict[str, object] = {
        "identity": {"canonical_id": CANONICAL_ID},
        "family_id": FAMILY_ID,
        "family_contract_version": FAMILY_CONTRACT_VERSION,
        "dataset_code": DATASET_CODE,
        "data_kind": DATA_KIND,
        "frequency": "1d",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "required_fields": list(REQUIRED_FIELDS),
        "adjustment": REQUEST_ADJUSTMENT,
        "price_basis": "close",
        "source_policy_id": SOURCE_POLICY_ID,
        "mode": mode,
        "purpose": "display",
        "currency": "CNY",
        "unit": "share",
    }
    return MarketDataQueryRequest.model_validate(payload)


def _source_policies(provider: _Provider) -> MarketDataSourcePolicyRegistry:
    route = MarketDataProviderRoute(
        route_id=ROUTE_ID,
        request_provider="ths",
        expected_result_provider_ids=frozenset({"ths"}),
        asset_types=frozenset({"stock"}),
        data_kinds=frozenset({"bars"}),
        frequencies=frozenset({"1d"}),
        markets=frozenset({"CN-SSE", "CN-SZSE"}),
        adjustments=frozenset({None, "unadjusted", "qfq", "hfq"}),
        price_bases=frozenset({None, "close"}),
        currencies=frozenset({None, "CNY"}),
        units=frozenset({None, "share"}),
        family_id=FAMILY_ID,
        family_contract_version=FAMILY_CONTRACT_VERSION,
        adapter=provider,
    )
    return MarketDataSourcePolicyRegistry(
        (
            MarketDataSourcePolicy(
                policy_id=SOURCE_POLICY_ID,
                allowed_purposes=frozenset({"display"}),
                routes=(route,),
            ),
        )
    )


async def _seed_prerequisites(
    session: AsyncSession,
    *,
    database_url: str,
    start: datetime,
    end: datetime,
) -> str:
    spec = MarketDataBootstrapSpec(storage=CanonicalStorageSpec.from_database_url(database_url))
    await MarketDataPlatformBootstrapper(session).bootstrap(spec)

    # THS provider registry row (bootstrap only seeds akshare/openbb).
    session.add(
        DgProvider(
            provider_id=PROVIDER_ID,
            name="同花顺金融数据 API",
            category="market_data",
            auth_type="api_key",
            api_key_env="THS_API_KEY",
            rate_limit=60,
            is_active=True,
        )
    )
    # THS source authorization row (disposable harness license placeholder).
    session.add(
        AssetDataSourceRegistry(
            source_id=PROVIDER_ID,
            asset_types=["stock"],
            jurisdictions=["CN"],
            license_status="APPROVED",
            allowed_uses=["DISPLAY"],
            redistribution_policy="NO_REDISTRIBUTION",
            derived_data_policy="ALLOWED",
            retention_policy="iteration198-harness-only",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
            enabled=True,
            updated_at=datetime.now(UTC),
        )
    )
    user = User(
        username="iteration198-ths-harness",
        email="iteration198-ths-harness@example.test",
        hashed_password="test-only-placeholder-hash",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    await session.execute(user_roles.insert().values(user_id=user.id, role=Role.USER.value))
    user_id = str(user.id)
    await session.commit()

    identity = InstrumentIdentity.model_validate(
        {
            "asset_type": "stock",
            "identity_level": "ASSET",
            "canonical_id": CANONICAL_ID,
            "display_symbol": DISPLAY_SYMBOL,
            "name": "Iteration 198 disposable acceptance instrument",
            "venue": VENUE,
            "currency": "CNY",
            "timezone": "Asia/Shanghai",
            "identifier_type": "EXCHANGE_SYMBOL",
            "identifier_value": "600519.SH",
            "product_type": "EQUITY",
            "metadata_version": "iteration198-harness-v1",
            "details": {"kind": "STOCK", "exchange_symbol": "600519.SH"},
        }
    )
    identity_writer = MarketDataIdentityWriter(session)
    await identity_writer.persist_identity(identity, valid_from=start - timedelta(days=365))
    await session.commit()
    await identity_writer.publish_staged()

    calendar_payload = {
        "manifest_version": MANIFEST_VERSION,
        "approval_reference": "ITER198-HARNESS-NONPRODUCTION",
        "evidence_uri": "file:///iteration198-harness/non-production-calendar.json",
        "evidence_content_hash": "0" * 64,
        "source_registry_id": PROVIDER_ID,
        "calendar_code": VENUE,
        "calendar_version": f"harness-{start.date().isoformat()}",
        "timezone_name": "Asia/Shanghai",
        "coverage_start_at": start.isoformat(),
        "coverage_end_at": end.isoformat(),
        "events": [
            {
                "trading_date": start.date().isoformat(),
                "event_type": "session",
                "session_code": "daily-bar-close",
                "is_trading_day": True,
                "event_start": start.isoformat(),
                "event_end": (end - timedelta(microseconds=1)).isoformat(),
                "coverage": {"data_kind": DATA_KIND, "frequency": "1d"},
                "event_payload": {"provider_observation_key": "daily-close"},
            }
        ],
    }
    await MarketDataCalendarImporter(session).import_payload(
        payload=calendar_payload, dry_run=False
    )
    await session.commit()
    return user_id


async def _access(session: AsyncSession, *, user_id: str) -> MarketDataQueryAccess:
    user = await session.get(User, user_id)
    if user is None:
        raise HarnessError("HARNESS_PREREQUISITES_UNAVAILABLE", stage="authorization")
    authorizer = MarketDataAccessAuthorizer(session)
    principal = await authorizer.principal_for_user(user)
    return MarketDataQueryAccess(principal=principal, authorizer=authorizer)


def _service(session: AsyncSession, provider: _Provider) -> MarketDataQueryService:
    return MarketDataQueryService(
        resolver=MarketDataQueryResolver(
            catalog=DataCatalogResolver(session),
            identities=MarketDataIdentityResolver(session),
        ),
        store=MarketDataStore(session),
        source_policies=_source_policies(provider),
        allow_online_fetch=True,
        cursor_signing_key="iteration198-disposable-local-cursor-key-0000000000000000000000000001",
    )


def _execution_summary(execution: MarketDataQueryExecution) -> dict[str, object]:
    return {
        "coverage_status": execution.coverage.status.value,
        "observation_count": len(execution.observations),
        "persisted_fetch_count": len(execution.fetches),
        "warning_codes": sorted(
            warning.code
            for warning in execution.warnings
            if _SAFE_WARNING_CODE.fullmatch(warning.code)
        ),
    }


async def _run_live(
    *,
    database_path: Path,
    trading_date: date,
    provider_factory: Callable[[], _Provider] | None = None,
) -> dict[str, object]:
    database_url = _database_url(database_path)
    engine: AsyncEngine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    start, end = _window_for(trading_date)
    factory = provider_factory or _live_provider_from_environment
    provider = _RecordingProvider(factory())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as seed_session:
            user_id = await _seed_prerequisites(
                seed_session, database_url=database_url, start=start, end=end
            )

        request = _request_for(start=start, end=end, mode="local_first")
        async with session_factory() as first_session:
            first = await _service(first_session, provider).execute(
                request, access=await _access(first_session, user_id=user_id)
            )
            await first_session.commit()

        base_summary: dict[str, object] = {
            "family_id": FAMILY_ID,
            "route_id": ROUTE_ID,
            "data_kind": DATA_KIND,
            "window_date": trading_date.isoformat(),
            "provider_fetch_attempt_count": provider.attempt_count,
            "first_local_first": _execution_summary(first),
            "credential_writes": False,
            "raw_payload_emitted": False,
        }
        if (
            first.coverage.status.value != "complete"
            or len(first.fetches) != 1
            or len(first.observations) < 1
        ):
            return {
                "status": "failed",
                "code": "THS_LOCAL_FIRST_INCOMPLETE",
                "stage": "live_fetch_or_persistence",
                **base_summary,
            }

        local_only_request = _request_for(start=start, end=end, mode="local_only")
        async with session_factory() as reread_session:
            reread_provider = _RecordingProvider(_UnexpectedProvider())
            reread = await _service(reread_session, reread_provider).execute(
                local_only_request, access=await _access(reread_session, user_id=user_id)
            )
            snapshot_count = await reread_session.scalar(
                select(func.count()).select_from(MdSourceSnapshot)
            )
            revision_count = await reread_session.scalar(
                select(func.count()).select_from(MdObservationRevision)
            )

        reread_summary = _execution_summary(reread)
        reread_summary["provider_fetch_attempt_count"] = reread_provider.attempt_count
        base_summary.update(
            {
                "independent_local_only_reread": reread_summary,
                "persistence": {
                    "source_snapshot_count": int(snapshot_count or 0),
                    "observation_revision_count": int(revision_count or 0),
                },
            }
        )
        if (
            reread.coverage.status.value != "complete"
            or reread.fetches
            or reread_provider.attempt_count != 0
            or len(reread.observations) < 1
        ):
            return {
                "status": "failed",
                "code": "THS_LOCAL_ONLY_REREAD_FAILED",
                "stage": "independent_local_only_reread",
                **base_summary,
            }
        return {"status": "pass", "code": "THS_LOCAL_FIRST_CHAIN_PASSED", **base_summary}
    finally:
        await engine.dispose()


def _live_provider_from_environment() -> _Provider:
    _load_env_file()
    provider = ThsProvider.from_environment()
    if provider is None:
        raise HarnessError("THS_AUTH_UNAVAILABLE", stage="provider_construction")
    return provider


def _load_env_file() -> None:
    """Load ``THS_API_KEY``/``THS_API_BASE_URL`` from the repo-root ``.env``.

    ``ThsProvider.from_environment`` reads ``os.environ`` directly, so the
    harness seeds only the THS credential reference (never database URLs) from
    the conventional ``.env`` location. Existing environment values win.
    """
    env_path = BACKEND_ROOT.parent.parent / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key in {"THS_API_KEY", "THS_API_BASE_URL"} and key not in os.environ:
                os.environ[key] = value
    except OSError:
        return


def _not_run_summary() -> dict[str, object]:
    return {
        "status": "not_run",
        "code": "LIVE_CONFIRMATION_REQUIRED",
        "network_called": False,
        "database_created": False,
        "credential_writes": False,
        "raw_payload_emitted": False,
    }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
        if args.mode != "live":
            _emit(_not_run_summary())
            return 0
        trading_date = _parse_trading_date(args.trading_date)
        target = _DatabaseTarget.allocate(args.database_path)
    except HarnessError as exc:
        _emit(
            {
                "status": "failed",
                "code": exc.code,
                "stage": exc.stage,
                "credential_writes": False,
                "raw_payload_emitted": False,
            }
        )
        return 2

    payload: dict[str, object]
    exit_code = 1
    cleanup_ok = False
    try:
        payload = asyncio.run(_run_live(database_path=target.path, trading_date=trading_date))
        exit_code = 0 if payload.get("status") == "pass" else 1
    except HarnessError as exc:
        payload = {"status": "failed", "code": exc.code, "stage": exc.stage}
    except Exception:
        payload = {
            "status": "failed",
            "code": "THS_ACCEPTANCE_HARNESS_FAILED",
            "stage": "harness_execution",
        }
    finally:
        cleanup_ok = target.cleanup()

    payload.update(
        {
            "database": {"kind": target.kind, "removed": cleanup_ok},
            "credential_writes": False,
            "raw_payload_emitted": False,
        }
    )
    if not cleanup_ok:
        payload["status"] = "failed"
        payload["code"] = "HARNESS_DATABASE_CLEANUP_FAILED"
        payload["stage"] = "cleanup"
        exit_code = 1
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
