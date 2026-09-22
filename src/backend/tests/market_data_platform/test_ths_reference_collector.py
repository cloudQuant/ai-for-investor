"""THS reference collector 的 fixture 测试（除复权因子 + 财务归一化）。"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.schemas.asset_research import InstrumentIdentity
from app.schemas.market_data_platform import MarketDataQueryRequest, ResolvedMarketDataQuery
from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.catalog import DatasetStorageResolution
from app.services.market_data.coverage import QueryIdentity
from app.services.market_data.identity import ResolvedMarketDataIdentity
from app.services.market_data.providers import MarketDataProviderRequest
from app.services.market_data.publication import MarketDataDeferredPublicationIntent
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.store import (
    DeferredProviderFetch,
    MarketDataStore,
    PersistedProviderFetch,
)
from app.services.market_data.ths_envelope import ThsEnvelope
from app.services.market_data.ths_reference_collector import (
    THS_ADJUSTMENT_FACTORS_DATASET_CODE,
    THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
    THS_FINANCIALS_SOURCE_POLICY_ID,
    THS_FINANCIALS_STATEMENTS,
    ThsReferenceCollector,
    ThsReferenceCollectorError,
    _millis_to_event_at,
    adjustment_factor_observations,
    financials_observations,
)

UTC = timezone.utc


def _request(
    *,
    source_policy_id: str = THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
    required_fields: frozenset[str] = frozenset({"dividend_per_share", "per_share_bonus"}),
) -> MarketDataProviderRequest:
    return MarketDataProviderRequest(
        query_fingerprint="a" * 64,
        canonical_id="instrument:stock:CN-SSE:600519",
        asset_type="stock",
        provider_symbol="600519.SH",
        market="CN-SSE",
        data_kind="reference_series",
        frequency="1d",
        start_at=datetime(2020, 1, 1, tzinfo=UTC),
        end_at=datetime(2026, 9, 20, tzinfo=UTC),
        required_fields=required_fields,
        provider="ths",
        source_policy_id=source_policy_id,
    )


def _context(
    *,
    dataset_code: str,
    source_policy_id: str,
    required_fields: frozenset[str],
) -> ResolvedMarketDataQueryContext:
    canonical_id = "instrument:stock:CN-SSE:600519"
    request = MarketDataQueryRequest.model_validate(
        {
            "identity": {"canonical_id": canonical_id},
            "dataset_code": dataset_code,
            "data_kind": "reference_series",
            "frequency": "1d",
            "start": "2020-01-01T00:00:00+00:00",
            "end": "2026-09-20T00:00:00+00:00",
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
        canonical_id=canonical_id,
        dataset_code=dataset_code,
        instrument_metadata_version="ths-reference-test-v1",
    )
    identity = InstrumentIdentity(
        asset_type="stock",
        identity_level="ASSET",
        canonical_id=canonical_id,
        display_symbol="600519.SH",
        name="Moutai",
        venue="CN-SSE",
        currency="CNY",
        timezone="Asia/Shanghai",
        identifier_type="EXCHANGE_SYMBOL",
        identifier_value="600519.SH",
        product_type="EQUITY",
        metadata_version="ths-reference-test-v1",
        details={"kind": "STOCK", "exchange_symbol": "600519.SH"},
    )
    return ResolvedMarketDataQueryContext(
        query=query,
        identity=ResolvedMarketDataIdentity(
            instrument_id=canonical_id,
            canonical_id=canonical_id,
            asset_type="stock",
            metadata_version="ths-reference-test-v1",
            venue="CN-SSE",
            identity=identity,
            valid_from=datetime(2000, 1, 1, tzinfo=UTC),
            valid_to=None,
            known_at=datetime(2000, 1, 1, tzinfo=UTC),
        ),
        storage=DatasetStorageResolution(
            dataset_id="dataset-ths-reference",
            dataset_code=dataset_code,
            storage_id="market-data",
            engine="sqlite",
            database_name="local",
            physical_table="md_observation_revisions",
            write_mode="canonical_read_write",
        ),
        coverage_identity=QueryIdentity(
            dataset_code=dataset_code,
            canonical_id=canonical_id,
            asset_type="stock",
            instrument_metadata_version="ths-reference-test-v1",
            data_kind="reference_series",
            market="CN-SSE",
            frequency="1d",
            source_policy_id=source_policy_id,
            adjustment="unadjusted",
            price_basis="close",
            currency="CNY",
            unit="share",
        ),
    )


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
        principal_scope="principal-v1:ths-reference-test",
        tenant_scope="default",
        entitlement_revision="b" * 64,
        decision="ALLOW",
        descriptor_hash="a" * 64,
    )


def _persisted_fetch() -> PersistedProviderFetch:
    return PersistedProviderFetch(
        series_id="series-ths-reference",
        source_snapshot_id="snapshot-ths-reference",
        observation_revision_ids=("revision-ths-reference",),
        passing_observation_count=1,
        failed_observation_count=0,
        received_at=datetime(2026, 9, 18, 8, tzinfo=UTC),
    )


def _deferred_fetch() -> DeferredProviderFetch:
    return DeferredProviderFetch(
        series_id="series-ths-reference",
        source_snapshot_id="snapshot-ths-reference",
        publication_id="publication-ths-reference",
        observation_revision_ids=("revision-ths-reference",),
        passing_observation_count=1,
        failed_observation_count=0,
        local_received_at=datetime(2026, 9, 18, 8, tzinfo=UTC),
        intent=MarketDataDeferredPublicationIntent(
            workflow_kind="legacy_stock_daily_import",
            intent_sha256="c" * 64,
        ),
    )


def _envelope() -> ThsEnvelope:
    # ex_date_ms 对应 2025-06-26 与 2024-12-30（Asia/Shanghai 零点）。
    return ThsEnvelope(
        code=0,
        message="success",
        request_id="req-1",
        data_item=(
            {
                "ticker": "600519",
                "ex_date_ms": 1782403200000,
                "dividend_per_share": 28.02,
                "per_share_bonus": 0,
            },
            {
                "ticker": "600519",
                "ex_date_ms": 1766073600000,
                "dividend_per_share": 23.95,
                "per_share_bonus": 0,
            },
        ),
        data_timestamp_ms=None,
        raw={},
    )


def test_event_time_is_utc_midnight_of_shanghai_date() -> None:
    """ex_date_ms 归一化为除权日的 UTC midnight。"""
    # 1782403200000 = 2026-06-26 00:00 Asia/Shanghai → 2026-06-25 16:00 UTC → 日期 2026-06-26
    event_at = _millis_to_event_at(1782403200000)
    assert event_at == datetime(2026, 6, 26, tzinfo=UTC)


def test_observations_descending_with_fields() -> None:
    """AC-12：除复权事件按 ex_date_ms 降序，字段映射正确。"""
    observations = adjustment_factor_observations(
        _envelope(),
        request=_request(),
        retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    assert len(observations) == 2
    # normalize_adjustment_factors 已降序，故第一条是较晚的 ex_date_ms。
    assert observations[0].event_at > observations[1].event_at
    assert observations[0].fields["dividend_per_share"] == 28.02
    assert observations[0].fields["per_share_bonus"] == 0


def test_null_fields_transparent() -> None:
    """null 字段透传不补零。"""
    envelope = ThsEnvelope(
        code=0,
        message="success",
        request_id="req-2",
        data_item=(
            {
                "ticker": "600519",
                "ex_date_ms": 1782403200000,
                "dividend_per_share": None,
                "per_share_bonus": 0,
            },
        ),
        data_timestamp_ms=None,
        raw={},
    )
    observations = adjustment_factor_observations(
        envelope,
        request=_request(),
        retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
    )
    assert observations[0].fields["dividend_per_share"] is None


def _financials_envelope() -> ThsEnvelope:
    # period_end_ms 对应 2024-12-31 与 2023-12-31（Asia/Shanghai 零点）。
    return ThsEnvelope(
        code=0,
        message="success",
        request_id="req-fin",
        data_item=(
            {
                "thscode": "600519.SH",
                "ticker": "600519",
                "period": "annual",
                "fiscal_year": 2024,
                "fiscal_period": "Q4",
                "report_date_ms": 1738368000000,
                "period_end_ms": 1735574400000,
                "currency": "CNY",
                "operating_income": 17089912345.67,
                "net_profit": 8622800000.0,
                "basic_eps": None,
            },
            {
                "thscode": "600519.SH",
                "ticker": "600519",
                "period": "annual",
                "fiscal_year": 2023,
                "fiscal_period": "Q4",
                "report_date_ms": 1706832000000,
                "period_end_ms": 1703952000000,
                "currency": "CNY",
                "operating_income": 14767700000.0,
                "net_profit": 7473400000.0,
                "basic_eps": 59.49,
            },
        ),
        data_timestamp_ms=None,
        raw={},
    )


class TestFinancials:
    def test_period_end_becomes_event_at(self) -> None:
        """event_at 为报告期末 period_end_ms 的 UTC midnight（AC-11）。"""
        observations = financials_observations(
            _financials_envelope(),
            request=_request(),
            retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        assert len(observations) == 2
        # normalize_financials 按 period_end 降序，第一条为 2024 年报。
        assert observations[0].event_at == datetime(2024, 12, 31, tzinfo=UTC)
        assert observations[1].event_at == datetime(2023, 12, 31, tzinfo=UTC)

    def test_dimension_fields_retained_and_null_transparent(self) -> None:
        """fiscal_year/fiscal_period 维度保留；basic_eps null 透传不补零。"""
        observations = financials_observations(
            _financials_envelope(),
            request=_request(),
            retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        assert observations[0].fields["fiscal_year"] == 2024
        assert observations[0].fields["fiscal_period"] == "Q4"
        assert observations[0].fields["basic_eps"] is None  # 2024 年报未披露
        assert observations[1].fields["basic_eps"] == 59.49
        # period_end_ms 已转为 event_at，不残留在 fields。
        assert "period_end_ms" not in observations[0].fields

    def test_out_of_window_periods_filtered(self) -> None:
        """窗口外的报告期被过滤。"""
        stale = ThsEnvelope(
            code=0,
            message="success",
            request_id="req-stale",
            data_item=(
                {
                    "period": "annual",
                    "fiscal_year": 2010,
                    "fiscal_period": "Q4",
                    "period_end_ms": 1293417600000,  # 2010-12-31（窗口外）
                    "operating_income": 1.0,
                },
            ),
            data_timestamp_ms=None,
            raw={},
        )
        observations = financials_observations(
            stale,
            request=_request(),  # start 2020-01-01
            retrieved_at=datetime(2026, 9, 18, tzinfo=UTC),
        )
        assert observations == ()

    def test_statements_registry_covers_three_reports(self) -> None:
        assert sorted(THS_FINANCIALS_STATEMENTS) == ["balance", "cashflow", "income"]


@pytest.mark.parametrize("method", ("adjustment_factors", "financials"))
@pytest.mark.parametrize("deferred", (False, True), ids=("persisted", "deferred"))
@pytest.mark.asyncio
async def test_reference_collector_requires_visible_store_receipt(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    deferred: bool,
) -> None:
    source_authorization = _source_authorization()
    retrieved_at = datetime(2026, 9, 18, tzinfo=UTC)
    if method == "adjustment_factors":
        dataset_code = THS_ADJUSTMENT_FACTORS_DATASET_CODE
        source_policy_id = THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID
        required_fields = frozenset({"dividend_per_share", "per_share_bonus"})
    else:
        dataset_code = THS_FINANCIALS_STATEMENTS["income"]
        source_policy_id = THS_FINANCIALS_SOURCE_POLICY_ID
        required_fields = frozenset({"operating_income", "net_profit"})
    context = _context(
        dataset_code=dataset_code,
        source_policy_id=source_policy_id,
        required_fields=required_fields,
    )
    receipt = _deferred_fetch() if deferred else _persisted_fetch()
    store = MarketDataStore.__new__(MarketDataStore)
    persist = AsyncMock(return_value=receipt)
    monkeypatch.setattr(store, "persist_provider_result", persist)
    collector = ThsReferenceCollector(store=store)
    request = _request(
        source_policy_id=source_policy_id,
        required_fields=required_fields,
    )

    if deferred:
        with pytest.raises(ThsReferenceCollectorError) as rejected:
            if method == "adjustment_factors":
                await collector.persist_adjustment_factors(
                    context=context,
                    source_authorization=source_authorization,
                    request=request,
                    envelope=_envelope(),
                    retrieved_at=retrieved_at,
                )
            else:
                await collector.persist_financials(
                    statement="income",
                    context=context,
                    source_authorization=source_authorization,
                    request=request,
                    envelope=_financials_envelope(),
                    retrieved_at=retrieved_at,
                )
        assert rejected.value.code == "THS_REFERENCE_PERSISTENCE_DEFERRED"
    else:
        if method == "adjustment_factors":
            result = await collector.persist_adjustment_factors(
                context=context,
                source_authorization=source_authorization,
                request=request,
                envelope=_envelope(),
                retrieved_at=retrieved_at,
            )
        else:
            result = await collector.persist_financials(
                statement="income",
                context=context,
                source_authorization=source_authorization,
                request=request,
                envelope=_financials_envelope(),
                retrieved_at=retrieved_at,
            )
        assert result is receipt

    persist.assert_awaited_once()
