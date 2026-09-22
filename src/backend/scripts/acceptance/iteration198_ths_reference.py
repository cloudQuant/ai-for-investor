# ruff: noqa: E402
"""Run an opt-in, disposable THS reference-collector acceptance probe.

Verifies the Iteration 198 sparse reference data path: fetch THS adjustment
factors for one A-share, persist them through ``ThsReferenceCollector`` into the
canonical ``md_observation_revisions`` store, then re-read them locally without
network.  Uses the schedule-only collector path (no request-time route, no
public family, no coverage grid), mirroring ``stock_valuation_collector``.

Default is a safe ``NOT_RUN``.  A live confirmation is explicit:

    /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base \
        python scripts/acceptance/iteration198_ths_reference.py --mode live
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx

import app.models  # noqa: F401
from app.db.database import Base
from app.models.asset_research import AssetDataSourceRegistry
from app.models.data_governance import DgProvider
from app.models.market_data_platform import MdObservationRevision, MdSourceSnapshot
from app.models.permission import Role, user_roles
from app.models.user import User
from app.schemas.asset_research import InstrumentIdentity
from app.schemas.market_data_platform import MarketDataQueryRequest, ResolvedMarketDataQuery
from app.services.market_data.access import (
    MarketDataSourceAuthorization,
)
from app.services.market_data.bootstrap import (
    CanonicalStorageSpec,
    MarketDataBootstrapSpec,
    MarketDataPlatformBootstrapper,
)
from app.services.market_data.master_data import MarketDataIdentityWriter
from app.services.market_data.providers import MarketDataProviderRequest
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.store import MarketDataStore
from app.services.market_data.ths_envelope import ThsEnvelope, parse_ths_envelope
from app.services.market_data.ths_reference_collector import (
    THS_ADJUSTMENT_FACTORS_DATASET_CODE,
    THS_ADJUSTMENT_FACTORS_PROVIDER_ID,
    THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS,
    THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
    ThsReferenceCollector,
)

UTC = timezone.utc
LOCAL_RECEIVED_AT = datetime(2026, 9, 18, 8, 0, tzinfo=UTC)
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")
_DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
CANONICAL_ID = "instrument:stock:CN-SSE:600519"
SYMBOL = "600519.SH"
VENUE = "CN-SSE"


class HarnessError(RuntimeError):
    def __init__(self, code: str, *, stage: str) -> None:
        self.code = code if _SAFE_CODE.fullmatch(code) else "THS_REFERENCE_HARNESS_FAILED"
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
            directory = Path(tempfile.mkdtemp(prefix="iteration198-ths-ref-"))
            path = directory / "market_data.sqlite3"
            kind = "temporary"
        else:
            path = _validate_path(requested_path)
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
        except (FileNotFoundError, OSError):
            removed = False
        for suffix in ("-journal", "-shm", "-wal"):
            try:
                sidecar = Path(f"{self.path}{suffix}")
                if stat.S_ISREG(sidecar.lstat().st_mode):
                    sidecar.unlink()
            except (FileNotFoundError, OSError):
                pass
        if self.kind == "temporary":
            try:
                self.path.parent.rmdir()
            except OSError:
                pass
        return removed


def _validate_path(value: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "://" in value:
        raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    raw_path = Path(value).expanduser()
    if not raw_path.is_absolute():
        raw_path = Path.cwd() / raw_path
    if raw_path.name in {"", ".", ".."} or raw_path.suffix.lower() not in _DATABASE_SUFFIXES:
        raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    if raw_path.is_symlink() or raw_path.exists():
        raise HarnessError("HARNESS_DATABASE_NOT_FRESH", stage="database_target")
    if not raw_path.parent.is_dir() or raw_path.parent.is_symlink():
        raise HarnessError("HARNESS_DATABASE_TARGET_UNSAFE", stage="database_target")
    return raw_path


def _load_env_file() -> None:
    env_path = BACKEND_ROOT.parent.parent / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in {"THS_API_KEY", "THS_API_BASE_URL"} and key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip()
    except OSError:
        return


def _database_url(path: Path) -> str:
    return str(URL.create(drivername="sqlite+aiosqlite", database=str(path)))


def _window() -> tuple[datetime, datetime]:
    # 查询窗口受 ``_MAX_DIRECT_BAR_WINDOWS`` 限制（1d 最多 3650 天）。
    # 落库近 ~9 年除权因子事件；更早历史需分批回填。
    return datetime(2017, 1, 1, tzinfo=UTC), datetime(2026, 9, 20, tzinfo=UTC)


def _build_context(
    *,
    dataset_code: str,
    required_fields: tuple[str, ...],
    source_policy_id: str,
) -> ResolvedMarketDataQueryContext:
    from app.services.market_data.catalog import DatasetStorageResolution
    from app.services.market_data.coverage import QueryIdentity
    from app.services.market_data.identity import ResolvedMarketDataIdentity

    start, end = _window()
    request = MarketDataQueryRequest.model_validate(
        {
            "identity": {"canonical_id": CANONICAL_ID},
            "dataset_code": dataset_code,
            "data_kind": "reference_series",
            "frequency": "1d",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "required_fields": sorted(required_fields),
            "adjustment": "unadjusted",
            "price_basis": "close",
            "currency": "CNY",
            "unit": "share",
            "source_policy_id": source_policy_id,
            "consistency": "display",
            "purpose": "display",
            "mode": "local_only",
        }
    )
    query = ResolvedMarketDataQuery.from_request(
        request,
        canonical_id=CANONICAL_ID,
        dataset_code=dataset_code,
        instrument_metadata_version="iteration198-ths-ref-v1",
    )
    identity = InstrumentIdentity(
        asset_type="stock",
        identity_level="ASSET",
        canonical_id=CANONICAL_ID,
        display_symbol=SYMBOL,
        name="Iteration 198 THS reference harness",
        venue=VENUE,
        currency="CNY",
        timezone="Asia/Shanghai",
        identifier_type="EXCHANGE_SYMBOL",
        identifier_value=SYMBOL,
        product_type="EQUITY",
        metadata_version="iteration198-ths-ref-v1",
        details={"kind": "STOCK", "exchange_symbol": SYMBOL},
    )
    resolved_identity = ResolvedMarketDataIdentity(
        instrument_id=f"instrument:stock:{VENUE}:{SYMBOL}",
        canonical_id=CANONICAL_ID,
        asset_type="stock",
        metadata_version="iteration198-ths-ref-v1",
        venue=VENUE,
        identity=identity,
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        valid_to=None,
        known_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    return ResolvedMarketDataQueryContext(
        query=query,
        identity=resolved_identity,
        storage=DatasetStorageResolution(
            # dataset_id 受 store 的 36 字符上限约束；用确定性短哈希。
            dataset_id=hashlib.sha256(dataset_code.encode("utf-8")).hexdigest()[:32],
            dataset_code=dataset_code,
            storage_id="canonical-market-data",
            engine="sqlite",
            database_name="market_data",
            physical_table="md_observation_revisions",
            write_mode="canonical_read_write",
        ),
        coverage_identity=QueryIdentity(
            dataset_code=dataset_code,
            canonical_id=CANONICAL_ID,
            asset_type="stock",
            instrument_metadata_version="iteration198-ths-ref-v1",
            data_kind="reference_series",
            market=VENUE,
            frequency="1d",
            source_policy_id=source_policy_id,
            adjustment="unadjusted",
            price_basis="close",
            currency="CNY",
            unit="share",
        ),
    )


def _source_authorization() -> MarketDataSourceAuthorization:
    values: dict[str, object] = {
        "source_registry_id": THS_ADJUSTMENT_FACTORS_PROVIDER_ID,
        "registry_updated_at": LOCAL_RECEIVED_AT.isoformat(),
        "asset_type": "stock",
        "market": VENUE,
        "purpose": "display",
        "license_status": "APPROVED",
        "allowed_uses": ("DISPLAY",),
        "jurisdictions": ("CN-SSE", "CN-SZSE"),
        "effective_from": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
        "effective_to": None,
        "retention_policy": "ITERATION198-HARNESS-ONLY",
        "retention_expires_at": None,
        "redistribution_policy": "NO_REDISTRIBUTION",
        "principal_scope": "principal-v1:ths-ref-harness",
        "tenant_scope": "default",
        "entitlement_revision": hashlib.sha256(b"ths-ref-entitlement").hexdigest(),
        "decision": "ALLOW",
    }
    descriptor_hash = hashlib.sha256(
        json.dumps(
            {"version": "market-data-source-authorization-v1", **values},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return MarketDataSourceAuthorization(descriptor_hash=descriptor_hash, **values)  # type: ignore[arg-type]


async def _seed(session: AsyncSession, database_url: str) -> None:
    spec = MarketDataBootstrapSpec(storage=CanonicalStorageSpec.from_database_url(database_url))
    await MarketDataPlatformBootstrapper(session).bootstrap(spec)
    session.add(
        DgProvider(
            provider_id=THS_ADJUSTMENT_FACTORS_PROVIDER_ID,
            name="同花顺金融数据 API",
            category="market_data",
            auth_type="api_key",
            api_key_env="THS_API_KEY",
            rate_limit=60,
            is_active=True,
        )
    )
    session.add(
        AssetDataSourceRegistry(
            source_id=THS_ADJUSTMENT_FACTORS_PROVIDER_ID,
            asset_types=["stock"],
            jurisdictions=["CN-SSE", "CN-SZSE"],
            license_status="APPROVED",
            allowed_uses=["DISPLAY"],
            redistribution_policy="NO_REDISTRIBUTION",
            derived_data_policy="ALLOWED",
            retention_policy="iteration198-harness-only",
            effective_from=datetime(2020, 1, 1, tzinfo=UTC),
            enabled=True,
            updated_at=LOCAL_RECEIVED_AT,
        )
    )
    user = User(
        username="iteration198-ths-ref-harness",
        email="iteration198-ths-ref-harness@example.test",
        hashed_password="test-only-placeholder-hash",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    await session.execute(user_roles.insert().values(user_id=user.id, role=Role.USER.value))
    await session.commit()

    identity = InstrumentIdentity.model_validate(
        {
            "asset_type": "stock",
            "identity_level": "ASSET",
            "canonical_id": CANONICAL_ID,
            "display_symbol": SYMBOL,
            "name": "Iteration 198 THS adjustment factors",
            "venue": VENUE,
            "currency": "CNY",
            "timezone": "Asia/Shanghai",
            "identifier_type": "EXCHANGE_SYMBOL",
            "identifier_value": SYMBOL,
            "product_type": "EQUITY",
            "metadata_version": "iteration198-ths-ref-v1",
            "details": {"kind": "STOCK", "exchange_symbol": SYMBOL},
        }
    )
    identity_writer = MarketDataIdentityWriter(session)
    await identity_writer.persist_identity(identity, valid_from=datetime(2020, 1, 1, tzinfo=UTC))
    await session.commit()
    await identity_writer.publish_staged()


async def _fetch_envelope(path: str, params: dict[str, object]) -> ThsEnvelope:
    """Fetch one THS reference endpoint and return the parsed envelope."""
    _load_env_file()
    key = os.environ.get("THS_API_KEY", "")
    if not key:
        raise HarnessError("THS_AUTH_UNAVAILABLE", stage="fetch")
    base = os.environ.get("THS_API_BASE_URL", "https://fuyao.aicubes.cn").rstrip("/")
    response = httpx.get(
        f"{base}{path}",
        params=params,
        headers={"X-api-key": key},
        timeout=20,
        trust_env=False,
    )
    if response.status_code != 200:
        raise HarnessError("THS_FETCH_HTTP_ERROR", stage="fetch")
    return parse_ths_envelope(json.loads(response.text))


# 财务三报表的核心必填字段（null 仅降级质量，不拒绝落库）。
_FINANCIALS_ENDPOINTS: dict[str, tuple[str, dict[str, object], tuple[str, ...]]] = {
    "income": (
        "/api/a-share/financials/income-statements",
        {"thscode": SYMBOL, "period": "annual", "limit": 10},
        ("operating_income", "net_profit"),
    ),
    "balance": (
        "/api/a-share/financials/balance-sheets",
        {"thscode": SYMBOL, "period": "annual", "limit": 10},
        ("assets_total", "holder_equity_total"),
    ),
    "cashflow": (
        "/api/a-share/financials/cash-flow-statements",
        {"thscode": SYMBOL, "period": "annual", "limit": 10},
        ("act_cash_flow_net",),
    ),
}


async def _run_live(database_path: Path) -> dict[str, object]:
    from app.services.market_data.ths_reference_collector import (
        THS_FINANCIALS_SOURCE_POLICY_ID,
        THS_FINANCIALS_STATEMENTS,
    )

    database_url = _database_url(database_path)
    engine: AsyncEngine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as seed_session:
            await _seed(seed_session, database_url)

        authorization = _source_authorization()
        retrieved_at = datetime.now(UTC)
        start, end = _window()
        domains: dict[str, object] = {}

        # ---- 除复权因子 ----
        envelope = await _fetch_envelope(
            "/api/a-share/corporate-actions/adjustment-factors", {"thscode": SYMBOL}
        )
        context = _build_context(
            dataset_code=THS_ADJUSTMENT_FACTORS_DATASET_CODE,
            required_fields=("dividend_per_share", "per_share_bonus"),
            source_policy_id=THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
        )
        provider_request = _provider_request_for(
            context=context,
            required_fields=THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS,
            source_policy_id=THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
            start=start,
            end=end,
        )
        async with session_factory() as persist_session:
            store = MarketDataStore(persist_session)
            collector = ThsReferenceCollector(store=store)
            persisted = await collector.persist_adjustment_factors(
                context=context,
                source_authorization=authorization,
                request=provider_request,
                envelope=envelope,
                retrieved_at=retrieved_at,
            )
            await persist_session.commit()
        domains["adjustment_factors"] = {
            "source_event_count": len(envelope.data_item),
            "persisted_observation_count": persisted.passing_observation_count,
        }

        # ---- 财务三报表 ----
        for statement, (path, params, required) in _FINANCIALS_ENDPOINTS.items():
            envelope = await _fetch_envelope(path, dict(params))
            dataset_code = THS_FINANCIALS_STATEMENTS[statement]
            context = _build_context(
                dataset_code=dataset_code,
                required_fields=required,
                source_policy_id=THS_FINANCIALS_SOURCE_POLICY_ID,
            )
            provider_request = _provider_request_for(
                context=context,
                required_fields=frozenset(required),
                source_policy_id=THS_FINANCIALS_SOURCE_POLICY_ID,
                start=start,
                end=end,
            )
            async with session_factory() as persist_session:
                store = MarketDataStore(persist_session)
                collector = ThsReferenceCollector(store=store)
                persisted = await collector.persist_financials(
                    statement=statement,
                    context=context,
                    source_authorization=authorization,
                    request=provider_request,
                    envelope=envelope,
                    retrieved_at=retrieved_at,
                )
                await persist_session.commit()
            domains[f"financials_{statement}"] = {
                "source_event_count": len(envelope.data_item),
                "persisted_observation_count": persisted.passing_observation_count,
            }

        # ---- 交易日历（复用 MarketDataCalendarImporter 已有路径） ----
        from app.models.market_data_platform import MdCalendarEvent
        from app.services.market_data.calendar_importer import (
            MANIFEST_VERSION,
            MarketDataCalendarImporter,
        )
        from app.services.market_data.ths_reference import (
            normalize_calendar,
            normalize_tickers,
            ths_calendar_to_manifest_payload,
        )

        calendar_envelope = await _fetch_envelope("/api/a-share/calendar/trading-days", {})
        calendar_rows = normalize_calendar(calendar_envelope)
        calendar_manifest = ths_calendar_to_manifest_payload(
            calendar_rows,
            source_registry_id=THS_ADJUSTMENT_FACTORS_PROVIDER_ID,
            calendar_code=VENUE,
            calendar_version=f"ths-{datetime.now(UTC).date().isoformat()}",
            approval_reference="ITER198-THS-HARNESS-NONPRODUCTION",
            evidence_uri="file:///iteration198-ths-harness/calendar.json",
            evidence_content_hash="0" * 64,
        )
        if calendar_manifest["manifest_version"] != MANIFEST_VERSION:
            raise HarnessError("THS_CALENDAR_MANIFEST_VERSION_MISMATCH", stage="calendar")
        async with session_factory() as calendar_session:
            await MarketDataCalendarImporter(calendar_session).import_payload(
                payload=calendar_manifest, dry_run=False
            )
            await calendar_session.commit()
        domains["trading_calendar"] = {"source_day_count": len(calendar_rows)}

        # ---- 标的检索（主数据补全：THS 检索 → 新标的 InstrumentIdentity 落库） ----
        from app.services.market_data.master_data import MarketDataIdentityWriter

        search_symbol = "000001.SZ"
        search_canonical_id = "instrument:stock:CN-SZSE:000001"
        ticker_envelope = await _fetch_envelope(
            "/api/meta/tickers/search", {"q": search_symbol.split(".")[0], "limit": 3}
        )
        ticker_rows = normalize_tickers(ticker_envelope)
        exact = next((row for row in ticker_rows if row.get("thscode") == search_symbol), None)
        if exact is None:
            raise HarnessError("THS_TICKER_NOT_RESOLVED", stage="tickers")
        search_identity = InstrumentIdentity.model_validate(
            {
                "asset_type": "stock",
                "identity_level": "ASSET",
                "canonical_id": search_canonical_id,
                "display_symbol": exact["thscode"],
                "name": exact.get("name") or "THS resolved instrument",
                "venue": "CN-SZSE",
                "currency": exact.get("currency") or "CNY",
                "timezone": "Asia/Shanghai",
                "identifier_type": "EXCHANGE_SYMBOL",
                "identifier_value": exact["thscode"],
                "product_type": "EQUITY",
                "metadata_version": "iteration198-ths-ref-v1",
                "details": {"kind": "STOCK", "exchange_symbol": exact["thscode"]},
            }
        )
        async with session_factory() as ticker_session:
            writer = MarketDataIdentityWriter(ticker_session)
            await writer.persist_identity(
                search_identity, valid_from=datetime(2020, 1, 1, tzinfo=UTC)
            )
            await ticker_session.commit()
            await writer.publish_staged()
        domains["tickers_search"] = {
            "resolved_symbol": search_symbol,
            "resolved_name": exact.get("name"),
        }

        # ---- 指数成分股（取数 + 归一化验证，catalog 快照语义登记） ----
        index_envelope = await _fetch_envelope(
            "/api/a-share-index/constituents/ths-stock-list", {"thscode": "000300.SH"}
        )
        constituents = [
            row.get("thscode")
            for row in index_envelope.data_item
            if isinstance(row.get("thscode"), str)
        ]
        domains["index_constituents"] = {"constituent_count": len(constituents)}

        async with session_factory() as verify_session:
            snapshot_count = await verify_session.scalar(
                select(func.count()).select_from(MdSourceSnapshot)
            )
            revision_count = await verify_session.scalar(
                select(func.count()).select_from(MdObservationRevision)
            )
            calendar_event_count = await verify_session.scalar(
                select(func.count()).select_from(MdCalendarEvent)
            )

        return {
            "status": "pass",
            "code": "THS_REFERENCE_COLLECTOR_CHAIN_PASSED",
            "domains": domains,
            "source_snapshot_count": int(snapshot_count or 0),
            "observation_revision_count": int(revision_count or 0),
            "calendar_event_count": int(calendar_event_count or 0),
            "credential_writes": False,
            "raw_payload_emitted": False,
        }
    finally:
        await engine.dispose()


def _provider_request_for(
    *,
    context: ResolvedMarketDataQueryContext,
    required_fields: frozenset[str],
    source_policy_id: str,
    start: datetime,
    end: datetime,
) -> MarketDataProviderRequest:
    return MarketDataProviderRequest(
        query_fingerprint=context.query.query_fingerprint,
        canonical_id=CANONICAL_ID,
        asset_type="stock",
        provider_symbol=SYMBOL,
        market=VENUE,
        data_kind="reference_series",
        frequency="1d",
        start_at=start,
        end_at=end,
        required_fields=required_fields,
        provider="ths",
        adjustment="unadjusted",
        price_basis="close",
        currency="CNY",
        unit="share",
        source_policy_id=source_policy_id,
    )


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("offline", "live"),
        default="offline",
        help="offline emits NOT_RUN; live fetches and persists one adjustment-factors batch.",
    )
    parser.add_argument("--database-path", metavar="PATH")
    return parser.parse_args(argv)


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    try:
        args = _arguments(argv)
        if args.mode != "live":
            _emit({"status": "not_run", "code": "LIVE_CONFIRMATION_REQUIRED"})
            return 0
        target = _DatabaseTarget.allocate(args.database_path)
    except HarnessError as exc:
        _emit({"status": "failed", "code": exc.code, "stage": exc.stage})
        return 2

    exit_code = 1
    cleanup_ok = False
    try:
        payload = asyncio.run(_run_live(target.path))
        exit_code = 0 if payload.get("status") == "pass" else 1
    except HarnessError as exc:
        payload = {"status": "failed", "code": exc.code, "stage": exc.stage}
    except Exception:
        payload = {
            "status": "failed",
            "code": "THS_REFERENCE_HARNESS_FAILED",
            "stage": "harness_execution",
        }
    finally:
        cleanup_ok = target.cleanup()

    payload.update({"database": {"kind": target.kind, "removed": cleanup_ok}})
    if not cleanup_ok:
        payload["status"] = "failed"
        payload["code"] = "HARNESS_DATABASE_CLEANUP_FAILED"
        exit_code = 1
    _emit(payload)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
