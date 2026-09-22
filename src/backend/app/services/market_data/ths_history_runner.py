"""THS 历史数据全量回填与每日增量的可复用 runner（迭代 199）。

职责：
- 幂等确保 THS 的 control-plane 前置（``dg_providers`` + ``asset_data_source_registry``）。
- 从 registry 行派生与 store 校验一致的 source authorization。
- 下载 ``market-dumps`` Parquet 并按标的落库（日 K 全量 / 复权因子全量）。
- 每日增量（``daily-k-10d``）。

CLI 脚本（``scripts/backfill_ths_history.py`` / ``scripts/collect_ths_daily.py``）与
调度服务复用本 runner；默认行为不写库，由调用方显式提交。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import TypedDict

from aiosqlite import Connection as AioSQLiteConnection
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset_research import AssetDataSourceRegistry
from app.models.data_governance import DgProvider
from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.catalog import DataCatalogResolver, DatasetStorageResolution
from app.services.market_data.providers import MarketDataProviderRequest
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.store import MarketDataStore
from app.services.market_data.ths_dump_importer import (
    THS_DAILY_K_DATASET_CODE,
    THS_DAILY_K_REQUIRED_FIELDS,
    THS_DAILY_K_SOURCE_POLICY_ID,
    THS_DUMP_PROVIDER_ID,
    ThsDumpDownloader,
    ThsDumpImporter,
    canonical_id_for_thscode,
    group_by_symbol,
    parse_daily_k_parquet,
    thscode_for_canonical_id,
)

_UTC = timezone.utc
THS_API_KEY_ENV = "THS_API_KEY"
THS_API_BASE_URL_ENV = "THS_API_BASE_URL"
DEFAULT_THS_API_BASE_URL = "https://fuyao.aicubes.cn"

# control-plane 行的固定字段（authorization 必须与之逐字段一致）。
THS_CONTROL_PLANE_UPDATED_AT = datetime(2026, 1, 1, tzinfo=_UTC)
THS_LICENSE_STATUS = "APPROVED"
THS_ALLOWED_USES = ["DISPLAY"]
THS_JURISDICTIONS = ["CN"]
THS_REDISTRIBUTION_POLICY = "NO_REDISTRIBUTION"
THS_DERIVED_DATA_POLICY = "ALLOWED"
THS_RETENTION_POLICY = "MARKET-DATA-PLATFORM-V1"
THS_EFFECTIVE_FROM = datetime(2020, 1, 1, tzinfo=_UTC)
_THS_CALENDAR_ENDPOINT_PATH = "/api/a-share/calendar/trading-days"

# 全量回填窗口 ≤ 10 年（受 `_MAX_DIRECT_BAR_WINDOWS` 约束），用 3640 天留出余量。
THS_FULL_HISTORY_DAYS = 3640
# 增量窗口：daily-k-10d 覆盖近 10 个交易日，用 20 天覆盖读取。
THS_INCREMENTAL_DAYS = 20

# 领域结果错误：单标的存在但无该数据（新股/无除权），跳过而非失败（NFR-06）。
_DOMAIN_SKIP_CODES = frozenset({"DATA_NOT_READY", "EMPTY_CONFIRMED", "UNSUPPORTED_IDENTITY"})
_THS_DUMP_AUTHORIZATION_PROBE_SYMBOLS = (
    ("CN-SSE", "600519.SH"),
    ("CN-SZSE", "000001.SZ"),
    ("CN-BJSE", "430047.BJ"),
)


class _ThsSourceAuthorizationValues(TypedDict):
    source_registry_id: str
    registry_updated_at: str
    asset_type: str
    market: str
    purpose: str
    license_status: str
    allowed_uses: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    effective_from: str
    effective_to: str | None
    retention_policy: str
    retention_expires_at: str | None
    redistribution_policy: str
    principal_scope: str
    tenant_scope: str
    entitlement_revision: str
    decision: str


class ThsHistoryError(RuntimeError):
    """THS 历史 runner 稳定错误码。"""

    def __init__(self, code: str, *, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ThsBatchReport:
    """一次批量采集的安全汇总（不含原始数据）。"""

    dataset_code: str
    dump_kind: str
    parsed_row_count: int
    symbol_count: int
    persisted_symbol_count: int
    persisted_observation_count: int
    skipped_symbol_count: int = 0


class ThsReferenceBatchReport(TypedDict):
    """一次逐标的 reference 回填的精确汇总结构。"""

    target_count: int
    persisted_symbol_count: int
    skipped_count: int
    failed_count: int
    failed_samples: list[str]


class ThsHistoryRunner:
    """编排 THS dump 下载、解析与落库。"""

    def __init__(
        self,
        session: AsyncSession,
        *,
        downloader: ThsDumpDownloader,
    ) -> None:
        if not isinstance(session, AsyncSession):
            raise TypeError("session must be an AsyncSession")
        if not isinstance(downloader, ThsDumpDownloader):
            raise TypeError("downloader must be a ThsDumpDownloader")
        self._session = session
        self._downloader = downloader
        self._catalog = DataCatalogResolver(session)
        self._store = MarketDataStore(session)
        self._importer = ThsDumpImporter(store=self._store, catalog=self._catalog)

    @classmethod
    def from_environment(cls, session: AsyncSession) -> ThsHistoryRunner:
        """从环境读取 THS API Key 构造 runner。"""
        api_key = os.environ.get(THS_API_KEY_ENV, "").strip()
        if not api_key:
            raise ThsHistoryError("THS_AUTH_UNAVAILABLE")
        base_url = os.environ.get(THS_API_BASE_URL_ENV, DEFAULT_THS_API_BASE_URL).strip()
        return cls(
            session,
            downloader=ThsDumpDownloader(
                api_key=api_key, base_url=base_url or DEFAULT_THS_API_BASE_URL
            ),
        )

    async def ensure_control_plane(self) -> AssetDataSourceRegistry:
        """幂等确保 THS 的 provider 与 source registry 行，返回 registry 行。"""
        provider = (
            await self._session.execute(
                select(DgProvider).where(DgProvider.provider_id == THS_DUMP_PROVIDER_ID)
            )
        ).scalar_one_or_none()
        if provider is None:
            self._session.add(
                DgProvider(
                    provider_id=THS_DUMP_PROVIDER_ID,
                    name="同花顺金融数据 API",
                    category="market_data",
                    auth_type="api_key",
                    api_key_env=THS_API_KEY_ENV,
                    rate_limit=60,
                    is_active=True,
                )
            )
        registry = (
            await self._session.execute(
                select(AssetDataSourceRegistry).where(
                    AssetDataSourceRegistry.source_id == THS_DUMP_PROVIDER_ID
                )
            )
        ).scalar_one_or_none()
        if registry is None:
            registry = AssetDataSourceRegistry(
                source_id=THS_DUMP_PROVIDER_ID,
                asset_types=["stock"],
                jurisdictions=list(THS_JURISDICTIONS),
                license_status=THS_LICENSE_STATUS,
                allowed_uses=list(THS_ALLOWED_USES),
                redistribution_policy=THS_REDISTRIBUTION_POLICY,
                derived_data_policy=THS_DERIVED_DATA_POLICY,
                retention_policy=THS_RETENTION_POLICY,
                effective_from=THS_EFFECTIVE_FROM,
                enabled=True,
                updated_at=THS_CONTROL_PLANE_UPDATED_AT,
            )
            self._session.add(registry)
        await self._session.flush()
        return registry

    def _source_authorization(
        self, registry: AssetDataSourceRegistry, *, market: str
    ) -> MarketDataSourceAuthorization:
        """从 registry 行派生与 store 校验一致的 source authorization。

        ``registry_updated_at`` 取表中实际值，避免 ``SOURCE_AUTHORIZATION_REGISTRY_STALE``。
        """
        updated_at = registry.updated_at
        if updated_at.tzinfo is None or updated_at.utcoffset() is None:
            updated_at = updated_at.replace(tzinfo=_UTC)
        else:
            updated_at = updated_at.astimezone(_UTC)
        values: _ThsSourceAuthorizationValues = {
            "source_registry_id": registry.source_id,
            "registry_updated_at": updated_at.isoformat(),
            "asset_type": "stock",
            "market": market,
            "purpose": "display",
            "license_status": str(registry.license_status).upper(),
            "allowed_uses": tuple(sorted(str(v).upper() for v in (registry.allowed_uses or []))),
            "jurisdictions": tuple(sorted(str(v).upper() for v in (registry.jurisdictions or []))),
            "effective_from": _as_utc_iso(registry.effective_from),
            "effective_to": None,
            "retention_policy": str(registry.retention_policy).upper(),
            "retention_expires_at": None,
            "redistribution_policy": str(registry.redistribution_policy).upper(),
            "principal_scope": "principal-v1:ths-history-runner",
            "tenant_scope": "default",
            "entitlement_revision": hashlib.sha256(b"ths-history-runner-entitlement").hexdigest(),
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
        return MarketDataSourceAuthorization(**values, descriptor_hash=descriptor_hash)

    def _venue_authorizations(
        self, registry: AssetDataSourceRegistry
    ) -> dict[str, MarketDataSourceAuthorization]:
        """循环前预生成按交易所的授权。

        逐标的循环内不能访问 ORM 对象：一次 ``rollback`` 会使其过期，随后属性
        读取会触发同步 IO 并在异步上下文中抛 ``MissingGreenlet``。
        """
        return {
            venue: self._source_authorization(registry, market=venue)
            for venue in ("CN-SSE", "CN-SZSE", "CN-BJSE")
        }

    async def _ensure_sqlite_outer_transaction(self) -> None:
        """Start SQLite's physical transaction before opening a savepoint.

        With aiosqlite's legacy transaction control, the first SAVEPOINT can
        otherwise become the outermost transaction; releasing it commits the
        symbol even if the session is later rolled back.
        """
        if self._session.get_bind().dialect.name != "sqlite":
            return
        connection = await self._session.connection()
        raw_connection = await connection.get_raw_connection()
        driver_connection = raw_connection.driver_connection
        if (
            isinstance(driver_connection, AioSQLiteConnection)
            and not driver_connection.in_transaction
        ):
            await connection.exec_driver_sql("BEGIN")

    async def backfill_daily_k(
        self,
        *,
        limit: int | None = None,
        as_of: datetime | None = None,
        cache_path: str | None = None,
        commit_every: int | None = 200,
        skip_existing: bool = True,
    ) -> ThsBatchReport:
        """全量回填日 K（``daily-k`` dump），按标的分批落库。

        - ``cache_path``：本地缓存已下载的 Parquet（避免重复下载 ~172 MB）。
        - ``skip_existing``：跳过本地已有 ``market.bars`` series 的标的（断点续跑）。
        - ``commit_every``：每处理 N 只提交一次，保证中断后可续。
        """
        return await self._collect_dump(
            dump_kind="daily-k",
            history_days=THS_FULL_HISTORY_DAYS,
            limit=limit,
            as_of=as_of,
            cache_path=cache_path,
            commit_every=commit_every,
            skip_existing=skip_existing,
        )

    async def collect_daily(
        self,
        *,
        limit: int | None = None,
        as_of: datetime | None = None,
        cache_path: str | None = None,
        commit_every: int | None = 200,
    ) -> ThsBatchReport:
        """每日增量：``daily-k-10d`` 覆盖近 10 个交易日。"""
        return await self._collect_dump(
            dump_kind="daily-k-10d",
            history_days=THS_INCREMENTAL_DAYS,
            limit=limit,
            as_of=as_of,
            cache_path=cache_path,
            commit_every=commit_every,
            skip_existing=False,
        )

    async def existing_daily_k_canonical_ids(self) -> set[str]:
        """本地已存在 ``market.bars`` series 的 canonical_id 集合（断点续跑用）。"""
        return await self._existing_canonical_ids(THS_DAILY_K_DATASET_CODE)

    async def _existing_canonical_ids(self, dataset_code: str) -> set[str]:
        """本地某 dataset 已有 series 的 canonical_id 集合。"""
        from app.models.data_governance import DgDataset
        from app.models.market_data_platform import MdDataSeries

        statement = (
            select(MdDataSeries.canonical_id)
            .join(DgDataset, DgDataset.id == MdDataSeries.dataset_id)
            .where(DgDataset.dataset_code == dataset_code)
        )
        rows = await self._session.execute(statement)
        return {str(value) for value in rows.scalars()}

    async def existing_daily_k_symbols(self) -> list[str]:
        """本地已回填日线的标的 thscode 清单（供逐标的回填复用）。"""
        canonical_ids = await self.existing_daily_k_canonical_ids()
        symbols = [s for cid in canonical_ids if (s := thscode_for_canonical_id(cid))]
        return sorted(symbols)

    async def backfill_adjustment_factors(
        self,
        *,
        symbols: list[str] | None = None,
        limit: int | None = None,
        commit_every: int | None = 100,
    ) -> ThsReferenceBatchReport:
        """逐标的回填除复权因子（reference_series 落库）。"""
        from app.services.market_data.ths_envelope import parse_ths_envelope
        from app.services.market_data.ths_reference_collector import (
            THS_ADJUSTMENT_FACTORS_DATASET_CODE,
            THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS,
            THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
            ThsReferenceCollector,
        )

        targets = symbols if symbols is not None else await self.existing_daily_k_symbols()
        if symbols is None:
            already = await self._existing_canonical_ids(THS_ADJUSTMENT_FACTORS_DATASET_CODE)
            targets = [t for t in targets if canonical_id_for_thscode(t)[0] not in already]
        if limit is not None:
            targets = targets[:limit]
        storage = await self._catalog.resolve_primary(THS_ADJUSTMENT_FACTORS_DATASET_CODE)
        registry = await self.ensure_control_plane()
        collector = ThsReferenceCollector(store=self._store)
        authorizations = self._venue_authorizations(registry)
        persisted = 0
        skipped: list[str] = []
        failed: list[str] = []
        for index, symbol in enumerate(targets):
            try:
                await self._ensure_sqlite_outer_transaction()
                async with self._session.begin_nested():
                    canonical_id, venue = canonical_id_for_thscode(symbol)
                    authorization = authorizations[venue]
                    context, request = self._reference_context_and_request(
                        dataset_code=THS_ADJUSTMENT_FACTORS_DATASET_CODE,
                        canonical_id=canonical_id,
                        display_symbol=symbol,
                        venue=venue,
                        required_fields=THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS,
                        source_policy_id=THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
                        storage=storage,
                    )
                    await self._store.ensure_source_authorization_before_provider_io(
                        context,
                        authorization,
                        provider_id=THS_DUMP_PROVIDER_ID,
                        checked_at=datetime.now(_UTC),
                    )
                    payload = self._downloader.fetch_ths_json(
                        "/api/a-share/corporate-actions/adjustment-factors",
                        params={"thscode": symbol},
                    )
                    envelope = parse_ths_envelope(payload)
                    await collector.persist_adjustment_factors(
                        context=context,
                        source_authorization=authorization,
                        request=request,
                        envelope=envelope,
                        retrieved_at=datetime.now(_UTC),
                    )
                persisted += 1
            except Exception as exc:  # noqa: BLE001 - 单标的失败不阻断整批（NFR-06）
                code = getattr(exc, "code", type(exc).__name__)
                if code in _DOMAIN_SKIP_CODES:
                    skipped.append(f"{symbol}:{code}")
                else:
                    failed.append(f"{symbol}:{code}")
            if commit_every and (index + 1) % commit_every == 0:
                await self._session.commit()
        return {
            "target_count": len(targets),
            "persisted_symbol_count": persisted,
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "failed_samples": failed[:5],
        }

    async def backfill_financials(
        self,
        *,
        statement: str,
        symbols: list[str] | None = None,
        limit: int | None = None,
        commit_every: int | None = 100,
    ) -> ThsReferenceBatchReport:
        """逐标的回填财务报表（income/balance/cashflow）。"""
        from app.services.market_data.ths_envelope import parse_ths_envelope
        from app.services.market_data.ths_reference_collector import (
            THS_FINANCIALS_SOURCE_POLICY_ID,
            THS_FINANCIALS_STATEMENTS,
            ThsReferenceCollector,
        )

        dataset_code = THS_FINANCIALS_STATEMENTS.get(statement)
        if dataset_code is None:
            raise ThsHistoryError("THS_FINANCIALS_STATEMENT_UNSUPPORTED")
        endpoints = {
            "income": "/api/a-share/financials/income-statements",
            "balance": "/api/a-share/financials/balance-sheets",
            "cashflow": "/api/a-share/financials/cash-flow-statements",
        }
        required = {
            "income": frozenset({"operating_income", "net_profit"}),
            "balance": frozenset({"assets_total", "holder_equity_total"}),
            "cashflow": frozenset({"act_cash_flow_net"}),
        }[statement]
        targets = symbols if symbols is not None else await self.existing_daily_k_symbols()
        if symbols is None:
            already = await self._existing_canonical_ids(dataset_code)
            targets = [t for t in targets if canonical_id_for_thscode(t)[0] not in already]
        if limit is not None:
            targets = targets[:limit]
        storage = await self._catalog.resolve_primary(dataset_code)
        registry = await self.ensure_control_plane()
        collector = ThsReferenceCollector(store=self._store)
        authorizations = self._venue_authorizations(registry)
        persisted = 0
        skipped: list[str] = []
        failed: list[str] = []
        for index, symbol in enumerate(targets):
            try:
                await self._ensure_sqlite_outer_transaction()
                async with self._session.begin_nested():
                    canonical_id, venue = canonical_id_for_thscode(symbol)
                    authorization = authorizations[venue]
                    context, request = self._reference_context_and_request(
                        dataset_code=dataset_code,
                        canonical_id=canonical_id,
                        display_symbol=symbol,
                        venue=venue,
                        required_fields=required,
                        source_policy_id=THS_FINANCIALS_SOURCE_POLICY_ID,
                        storage=storage,
                    )
                    await self._store.ensure_source_authorization_before_provider_io(
                        context,
                        authorization,
                        provider_id=THS_DUMP_PROVIDER_ID,
                        checked_at=datetime.now(_UTC),
                    )
                    payload = self._downloader.fetch_ths_json(
                        endpoints[statement],
                        params={"thscode": symbol, "period": "annual", "limit": 20},
                    )
                    envelope = parse_ths_envelope(payload)
                    await collector.persist_financials(
                        statement=statement,
                        context=context,
                        source_authorization=authorization,
                        request=request,
                        envelope=envelope,
                        retrieved_at=datetime.now(_UTC),
                    )
                persisted += 1
            except Exception as exc:  # noqa: BLE001 - 单标的失败不阻断整批（NFR-06）
                code = getattr(exc, "code", type(exc).__name__)
                if code in _DOMAIN_SKIP_CODES:
                    skipped.append(f"{symbol}:{code}")
                else:
                    failed.append(f"{symbol}:{code}")
            if commit_every and (index + 1) % commit_every == 0:
                await self._session.commit()
        return {
            "target_count": len(targets),
            "persisted_symbol_count": persisted,
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "failed_samples": failed[:5],
        }

    def _reference_context_and_request(
        self,
        *,
        dataset_code: str,
        canonical_id: str,
        display_symbol: str,
        venue: str,
        required_fields: frozenset[str],
        source_policy_id: str,
        storage: DatasetStorageResolution,
        data_kind: str = "reference_series",
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> tuple[ResolvedMarketDataQueryContext, MarketDataProviderRequest]:
        """构造对应数据域的 canonical context 与 provider request。"""
        from app.services.market_data.ths_dump_importer import (
            _build_context,
            _provider_request,
        )

        if window_start is None and window_end is None:
            window_start = datetime(2017, 1, 1, tzinfo=_UTC)
            window_end = datetime.combine(
                datetime.now(_UTC).date() + timedelta(days=1), time.min, tzinfo=_UTC
            )
        elif window_start is None or window_end is None:
            raise ThsHistoryError("THS_HISTORY_REQUEST_WINDOW_INVALID")
        context = _build_context(
            dataset_code=dataset_code,
            data_kind=data_kind,
            canonical_id=canonical_id,
            display_symbol=display_symbol,
            venue=venue,
            required_fields=required_fields,
            source_policy_id=source_policy_id,
            storage=storage,
            window_start=window_start,
            window_end=window_end,
        )
        request = _provider_request(
            context=context,
            provider_symbol=display_symbol,
            data_kind=data_kind,
            required_fields=required_fields,
            source_policy_id=source_policy_id,
            window_start=window_start,
            window_end=window_end,
        )
        return context, request

    async def sync_calendar(self, *, as_of: datetime | None = None, apply: bool = False) -> int:
        """同步 A 股交易日历；默认只预览，显式 apply 才发布并持久化。"""
        if apply and self._session.in_transaction():
            raise ThsHistoryError("CALENDAR_PUBLICATION_REQUIRES_CLEAN_SESSION")

        from app.services.market_data.calendar_importer import (
            MarketDataCalendarImporter,
        )
        from app.services.market_data.ths_envelope import parse_ths_envelope
        from app.services.market_data.ths_reference import (
            normalize_calendar,
            ths_calendar_to_manifest_payload,
        )

        anchor = as_of or datetime.now(_UTC)
        window_end = datetime.combine(anchor.date() + timedelta(days=1), time.min, tzinfo=_UTC)
        caller_owned_transaction = not apply and self._session.in_transaction()
        dry_run_savepoint = None
        if not apply:
            if caller_owned_transaction:
                await self._ensure_sqlite_outer_transaction()
                dry_run_savepoint = await self._session.begin_nested()
            else:
                await self._session.begin()

        try:
            storage = await self._catalog.resolve_primary(THS_DAILY_K_DATASET_CODE)
            registry = await self.ensure_control_plane()
            authorization = self._venue_authorizations(registry)["CN-SSE"]
            context, request = self._reference_context_and_request(
                dataset_code=THS_DAILY_K_DATASET_CODE,
                canonical_id="instrument:stock:CN-SSE:600519",
                display_symbol="600519.SH",
                venue="CN-SSE",
                required_fields=THS_DAILY_K_REQUIRED_FIELDS,
                source_policy_id=THS_DAILY_K_SOURCE_POLICY_ID,
                storage=storage,
                data_kind="bars",
                window_start=datetime(2017, 1, 1, tzinfo=_UTC),
                window_end=window_end,
            )
            if request.provider != THS_DUMP_PROVIDER_ID or request.market != "CN-SSE":
                raise ThsHistoryError("THS_HISTORY_REQUEST_CONTEXT_MISMATCH")
            await self._store.ensure_source_authorization_before_provider_io(
                context,
                authorization,
                provider_id=THS_DUMP_PROVIDER_ID,
                checked_at=datetime.now(_UTC),
            )

            payload = self._downloader.fetch_ths_json(_THS_CALENDAR_ENDPOINT_PATH)
            envelope = parse_ths_envelope(payload)
            rows = normalize_calendar(envelope)
            evidence_content_hash = _canonical_ths_calendar_response_hash(rows)
            manifest = ths_calendar_to_manifest_payload(
                rows,
                source_registry_id=THS_DUMP_PROVIDER_ID,
                calendar_code="CN-SSE",
                calendar_version=f"ths-{anchor.date().isoformat()}",
                approval_reference="ITER199-THS-HISTORY-RUNNER",
                evidence_uri=f"{self._downloader._base_url}{_THS_CALENDAR_ENDPOINT_PATH}",
                evidence_content_hash=evidence_content_hash,
            )
            importer = MarketDataCalendarImporter(self._session)
            if apply:
                # Calendar publication requires a clean session. Commit the
                # explicitly-authorized control-plane preflight only after the
                # provider response has been validated.
                await self._session.commit()
                report = await importer.import_payload(payload=manifest, dry_run=False)
            else:
                report = await importer.import_payload(payload=manifest, dry_run=True)
        except BaseException:
            if apply and self._session.in_transaction():
                await self._session.rollback()
            raise
        finally:
            if not apply:
                if dry_run_savepoint is not None:
                    await dry_run_savepoint.rollback()
                elif self._session.in_transaction():
                    await self._session.rollback()
        return report.event_count

    async def _collect_dump(
        self,
        *,
        dump_kind: str,
        history_days: int,
        limit: int | None,
        as_of: datetime | None,
        cache_path: str | None,
        commit_every: int | None,
        skip_existing: bool,
    ) -> ThsBatchReport:
        anchor = as_of or datetime.now(_UTC)
        window_end = datetime.combine(anchor.date() + timedelta(days=1), time.min, tzinfo=_UTC)
        window_start = window_end - timedelta(days=history_days)
        storage = await self._catalog.resolve_primary(THS_DAILY_K_DATASET_CODE)
        registry = await self.ensure_control_plane()
        authorizations = self._venue_authorizations(registry)
        for venue, probe_symbol in _THS_DUMP_AUTHORIZATION_PROBE_SYMBOLS:
            canonical_id, symbol_venue = canonical_id_for_thscode(probe_symbol)
            if symbol_venue != venue:
                raise ThsHistoryError("THS_HISTORY_AUTHORIZATION_CONTEXT_INVALID")
            context, request = self._reference_context_and_request(
                dataset_code=THS_DAILY_K_DATASET_CODE,
                canonical_id=canonical_id,
                display_symbol=probe_symbol,
                venue=venue,
                required_fields=THS_DAILY_K_REQUIRED_FIELDS,
                source_policy_id=THS_DAILY_K_SOURCE_POLICY_ID,
                storage=storage,
                data_kind="bars",
                window_start=window_start,
                window_end=window_end,
            )
            if (
                request.provider != THS_DUMP_PROVIDER_ID
                or request.market != venue
                or request.canonical_id != canonical_id
            ):
                raise ThsHistoryError("THS_HISTORY_REQUEST_CONTEXT_MISMATCH")
            await self._store.ensure_source_authorization_before_provider_io(
                context,
                authorizations[venue],
                provider_id=THS_DUMP_PROVIDER_ID,
                checked_at=datetime.now(_UTC),
            )
        content = self._downloader.fetch_dump(dump_kind, cache_path=cache_path)
        bars = parse_daily_k_parquet(content)
        grouped = group_by_symbol(bars)
        symbols = sorted(grouped)
        if skip_existing:
            already = await self.existing_daily_k_canonical_ids()
            symbols = [s for s in symbols if canonical_id_for_thscode(s)[0] not in already]
        if limit is not None:
            symbols = symbols[:limit]
        persisted_symbols = 0
        persisted_observations = 0
        skipped: list[str] = []
        for index, symbol in enumerate(symbols):
            try:
                symbol_observation_count = 0
                symbol_persisted_count = 0
                await self._ensure_sqlite_outer_transaction()
                async with self._session.begin_nested():
                    venue = canonical_id_for_thscode(symbol)[1]
                    authorization = authorizations[venue]
                    persisted = await self._importer.import_daily_k(
                        bars_by_symbol={symbol: grouped[symbol]},
                        source_authorization=authorization,
                        retrieved_at=anchor,
                        window_start=window_start,
                        window_end=window_end,
                    )
                    for item in persisted:
                        symbol_persisted_count += 1
                        symbol_observation_count += item.passing_observation_count
                persisted_symbols += symbol_persisted_count
                persisted_observations += symbol_observation_count
            except Exception as exc:  # noqa: BLE001 - 单标的失败不阻断整批（NFR-06）
                code = getattr(exc, "code", type(exc).__name__)
                skipped.append(f"{symbol}:{code}")
            if commit_every and (index + 1) % commit_every == 0:
                await self._session.commit()
        return ThsBatchReport(
            dataset_code=THS_DAILY_K_DATASET_CODE,
            dump_kind=dump_kind,
            parsed_row_count=len(bars),
            symbol_count=len(grouped),
            persisted_symbol_count=persisted_symbols,
            persisted_observation_count=persisted_observations,
            skipped_symbol_count=len(skipped),
        )


def _as_utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=_UTC)
    return value.astimezone(_UTC).isoformat()


def _canonical_ths_calendar_response_hash(calendar_rows: object) -> str:
    """Hash stable normalized calendar response data, excluding transport metadata.

    The evidence URI names the THS endpoint, not a persisted raw-response artifact.
    """
    if not isinstance(calendar_rows, (list, tuple)) or not calendar_rows:
        raise ThsHistoryError("THS_CALENDAR_EVIDENCE_INVALID")
    dated_rows: list[tuple[int, str]] = []
    for row in calendar_rows:
        if not isinstance(row, Mapping):
            raise ThsHistoryError("THS_CALENDAR_EVIDENCE_INVALID")
        date_ms = row.get("date_ms")
        date = row.get("date")
        if not isinstance(date_ms, int) or isinstance(date_ms, bool) or not isinstance(date, str):
            raise ThsHistoryError("THS_CALENDAR_EVIDENCE_INVALID")
        dated_rows.append((date_ms, date))
    dated_rows.sort(key=lambda item: item[0])
    canonical_rows = [{"date_ms": date_ms, "date": date} for date_ms, date in dated_rows]
    try:
        canonical_json = json.dumps(
            {"calendar_rows": canonical_rows},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ThsHistoryError("THS_CALENDAR_EVIDENCE_INVALID") from exc
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
