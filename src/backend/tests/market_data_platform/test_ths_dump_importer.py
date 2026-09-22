"""THS market-dumps Parquet 解析与落库辅助函数的 fixture 测试。"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.catalog import DataCatalogResolver, DatasetStorageResolution
from app.services.market_data.publication import MarketDataDeferredPublicationIntent
from app.services.market_data.store import (
    DeferredProviderFetch,
    MarketDataStore,
    PersistedProviderFetch,
)
from app.services.market_data.ths_dump_importer import (
    DumpDailyBar,
    ThsDumpDownloader,
    ThsDumpError,
    ThsDumpImporter,
    canonical_id_for_thscode,
    group_by_symbol,
    parse_adjustment_factors_parquet,
    parse_daily_k_parquet,
)

UTC = timezone.utc


def _source_authorization() -> MarketDataSourceAuthorization:
    return MarketDataSourceAuthorization(
        source_registry_id="ths",
        registry_updated_at=datetime(2026, 9, 18, tzinfo=UTC).isoformat(),
        asset_type="stock",
        market="CN-SSE",
        purpose="display",
        license_status="APPROVED",
        allowed_uses=("DISPLAY",),
        jurisdictions=("CN-SSE",),
        effective_from=datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
        effective_to=None,
        retention_policy="MARKET-DATA-V1",
        retention_expires_at=None,
        redistribution_policy="NO_REDISTRIBUTION",
        principal_scope="principal-v1:ths-dump-test",
        tenant_scope="default",
        entitlement_revision="b" * 64,
        decision="ALLOW",
        descriptor_hash="a" * 64,
    )


def _persisted_fetch() -> PersistedProviderFetch:
    return PersistedProviderFetch(
        series_id="series-ths-dump",
        source_snapshot_id="snapshot-ths-dump",
        observation_revision_ids=("revision-ths-dump",),
        passing_observation_count=1,
        failed_observation_count=0,
        received_at=datetime(2026, 9, 18, 8, tzinfo=UTC),
    )


def _deferred_fetch() -> DeferredProviderFetch:
    return DeferredProviderFetch(
        series_id="series-ths-dump",
        source_snapshot_id="snapshot-ths-dump",
        publication_id="publication-ths-dump",
        observation_revision_ids=("revision-ths-dump",),
        passing_observation_count=1,
        failed_observation_count=0,
        local_received_at=datetime(2026, 9, 18, 8, tzinfo=UTC),
        intent=MarketDataDeferredPublicationIntent(
            workflow_kind="legacy_stock_daily_import",
            intent_sha256="c" * 64,
        ),
    )


def _fake_importer(
    monkeypatch: pytest.MonkeyPatch,
    persistence_result: PersistedProviderFetch | DeferredProviderFetch,
) -> tuple[ThsDumpImporter, AsyncMock]:
    storage = DatasetStorageResolution(
        dataset_id="dataset-ths-dump",
        dataset_code="market.bars",
        storage_id="market-data",
        engine="sqlite",
        database_name="local",
        physical_table="md_observation_revisions",
        write_mode="canonical_read_write",
    )
    catalog = DataCatalogResolver.__new__(DataCatalogResolver)
    monkeypatch.setattr(
        catalog,
        "resolve_primary",
        AsyncMock(return_value=storage),
    )
    store = MarketDataStore.__new__(MarketDataStore)
    persist = AsyncMock(return_value=persistence_result)
    monkeypatch.setattr(store, "persist_provider_result", persist)
    return ThsDumpImporter(store=store, catalog=catalog), persist


def _daily_k_parquet_bytes(rows: list[dict]) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq

    schema = pa.schema(
        [
            ("thscode", pa.string()),
            ("currency", pa.string()),
            ("interval", pa.string()),
            ("adjusted", pa.string()),
            ("date_ms", pa.int64()),
            ("open_price", pa.float64()),
            ("high_price", pa.float64()),
            ("low_price", pa.float64()),
            ("close_price", pa.float64()),
            ("volume", pa.float64()),
            ("turnover", pa.float64()),
        ]
    )
    table = pa.Table.from_pylist(rows, schema=schema)
    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    return buffer.getvalue()


class TestSessionSemantics:
    def test_canonical_id_derivation(self) -> None:
        assert canonical_id_for_thscode("600519.SH") == (
            "instrument:stock:CN-SSE:600519",
            "CN-SSE",
        )
        assert canonical_id_for_thscode("000001.SZ") == (
            "instrument:stock:CN-SZSE:000001",
            "CN-SZSE",
        )

    def test_canonical_id_rejects_unknown_suffix(self) -> None:
        with pytest.raises(ThsDumpError):
            canonical_id_for_thscode("600519.XX")
        with pytest.raises(ThsDumpError):
            canonical_id_for_thscode("600519")


class TestDailyKParse:
    def test_parse_and_date_ms_normalization(self) -> None:
        """date_ms（交易日上海零点）→ 交易日 UTC midnight（不减一天）。"""
        # 1789660800000 = 2026-09-18 00:00 Asia/Shanghai（周五，交易日）。
        content = _daily_k_parquet_bytes(
            [
                {
                    "thscode": "600519.SH",
                    "currency": "CNY",
                    "interval": "1d",
                    "adjusted": "none",
                    "date_ms": 1789660800000,
                    "open_price": 1262.99,
                    "high_price": 1265.88,
                    "low_price": 1256.1,
                    "close_price": 1257.12,
                    "volume": 2489087.0,
                    "turnover": 3135849108.35,
                }
            ]
        )
        bars = parse_daily_k_parquet(content)
        assert len(bars) == 1
        assert bars[0].thscode == "600519.SH"
        assert bars[0].event_at == datetime(2026, 9, 18, tzinfo=UTC)
        assert bars[0].close_price == 1257.12

    def test_group_by_symbol(self) -> None:
        bars = (
            DumpDailyBar("600519.SH", datetime(2026, 9, 18, tzinfo=UTC), 1, 1, 1, 1, 1, 1),
            DumpDailyBar("000001.SZ", datetime(2026, 9, 18, tzinfo=UTC), 1, 1, 1, 1, 1, 1),
            DumpDailyBar("600519.SH", datetime(2026, 9, 17, tzinfo=UTC), 1, 1, 1, 1, 1, 1),
        )
        grouped = group_by_symbol(bars)
        assert set(grouped) == {"600519.SH", "000001.SZ"}
        assert len(grouped["600519.SH"]) == 2

    def test_schema_mismatch_rejected(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist([{"foo": 1}])
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        with pytest.raises(ThsDumpError) as exc:
            parse_daily_k_parquet(buffer.getvalue())
        assert exc.value.code == "THS_DUMP_SCHEMA_MISMATCH"


class TestAdjustmentFactorsParse:
    def test_parse_ex_date(self) -> None:
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist(
            [
                {
                    "thscode": "600519.SH",
                    "ticker": "600519",
                    "ex_date_ms": 1782403200000,  # 2026-06-26 上海
                    "dividend_per_share": 28.02,
                    "per_share_bonus": 0.0,
                    "allotment_ratio": None,
                    "allotment_price": None,
                    "currency": "CNY",
                }
            ]
        )
        buffer = io.BytesIO()
        pq.write_table(table, buffer)
        factors = parse_adjustment_factors_parquet(buffer.getvalue())
        assert len(factors) == 1
        assert factors[0].event_at == datetime(2026, 6, 26, tzinfo=UTC)
        assert factors[0].dividend_per_share == 28.02


class TestDownloaderGuards:
    def test_missing_api_key_rejected(self) -> None:
        with pytest.raises(ThsDumpError):
            ThsDumpDownloader(api_key="")

    def test_unregistered_kind_rejected(self) -> None:
        downloader = ThsDumpDownloader(api_key="k")
        with pytest.raises(ThsDumpError) as exc:
            downloader.fetch_dump("nonexistent")
        assert exc.value.code == "THS_DUMP_KIND_UNREGISTERED"


@pytest.mark.asyncio
async def test_import_daily_k_returns_visible_store_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = _persisted_fetch()
    importer, persist = _fake_importer(monkeypatch, receipt)
    retrieved_at = datetime(2026, 9, 18, 8, tzinfo=UTC)
    bar = DumpDailyBar("600519.SH", datetime(2026, 9, 18, tzinfo=UTC), 1, 2, 1, 2, 3, 4)

    result = await importer.import_daily_k(
        bars_by_symbol={"600519.SH": (bar,)},
        source_authorization=_source_authorization(),
        retrieved_at=retrieved_at,
        window_start=datetime(2026, 9, 18, tzinfo=UTC),
        window_end=datetime(2026, 9, 19, tzinfo=UTC),
    )

    assert result == [receipt]
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_daily_k_rejects_deferred_store_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    importer, persist = _fake_importer(monkeypatch, _deferred_fetch())
    retrieved_at = datetime(2026, 9, 18, 8, tzinfo=UTC)
    bar = DumpDailyBar("600519.SH", datetime(2026, 9, 18, tzinfo=UTC), 1, 2, 1, 2, 3, 4)

    with pytest.raises(ThsDumpError) as rejected:
        await importer.import_daily_k(
            bars_by_symbol={"600519.SH": (bar,)},
            source_authorization=_source_authorization(),
            retrieved_at=retrieved_at,
            window_start=datetime(2026, 9, 18, tzinfo=UTC),
            window_end=datetime(2026, 9, 19, tzinfo=UTC),
        )

    assert rejected.value.code == "THS_DUMP_PERSISTENCE_DEFERRED"
    persist.assert_awaited_once()
