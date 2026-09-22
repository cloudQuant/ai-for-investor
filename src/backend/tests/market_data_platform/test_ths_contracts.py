"""THS 契约、复权、窗口、身份与 reference 归一化的 fixture 测试（AC-10~14）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.market_data.provider_contracts import ProviderContractError
from app.services.market_data.providers import MarketDataProviderRequest
from app.services.market_data.ths_contracts import (
    THS_PROVIDER_CONTRACT_REGISTRY,
    THS_SUPPORTED_INTERVALS,
    prepare_ths_historical_request,
    split_thscodes_batch,
    split_window_into_chunks,
    ths_adjustment,
)
from app.services.market_data.ths_envelope import ThsEnvelope
from app.services.market_data.ths_reference import (
    ThsReferenceError,
    build_adjustment_factors_request,
    build_financials_request,
    build_tickers_list_request,
    build_tickers_search_request,
    normalize_adjustment_factors,
    normalize_calendar,
    normalize_financials,
    normalize_tickers,
)

UTC = timezone.utc


def _request(**changes: object) -> MarketDataProviderRequest:
    values: dict[str, object] = {
        "query_fingerprint": "a" * 64,
        "canonical_id": "instrument:stock:CN-SSE:600519",
        "asset_type": "stock",
        "provider_symbol": "600519.SH",
        "market": "CN-SSE",
        "data_kind": "bars",
        "frequency": "1d",
        "start_at": datetime(2026, 1, 2, tzinfo=UTC),
        "end_at": datetime(2026, 1, 4, tzinfo=UTC),
        "required_fields": frozenset({"close"}),
        "provider": "ths",
        "route_id": "ths-stock-primary-v1",
        "family_id": "stock.realtime",
        "family_contract_version": "market-data-family-v1",
        "request_id": "A" * 43,
    }
    values.update(changes)
    return MarketDataProviderRequest(**values)  # type: ignore[arg-type]


class TestAdjustmentMapping:
    @pytest.mark.parametrize(
        "adjustment,expected",
        [("unadjusted", "none"), ("qfq", "forward"), ("hfq", "backward"), (None, "none")],
    )
    def test_adjustment_mapping(self, adjustment: str | None, expected: str) -> None:
        """AC-09 前置：中台复权语义 → THS 原生值显式映射。"""
        request = _request(adjustment=adjustment)
        assert ths_adjustment(request) == expected

    def test_unsupported_adjustment_rejected(self) -> None:
        with pytest.raises(ProviderContractError):
            ths_adjustment(_request(adjustment="source_reported"))


class TestWindowChunking:
    def test_window_under_10y_returns_single_chunk(self) -> None:
        """AC-10 部分：≤10 年单块。"""
        start = datetime(2020, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        chunks = split_window_into_chunks(start, end)
        assert chunks == ((start, end),)

    def test_window_over_10y_splits_into_bounded_chunks(self) -> None:
        """AC-10：>10 年自动切块，每块 ≤ 10 年。"""
        start = datetime(2000, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        chunks = split_window_into_chunks(start, end)
        assert len(chunks) > 1
        for chunk_start, chunk_end in chunks:
            assert chunk_end - chunk_start <= timedelta(days=365 * 10)
        assert chunks[0][0] == start
        assert chunks[-1][1] == end
        # 连续无缝隙。
        for (_, prev_end), (next_start, _) in zip(chunks, chunks[1:], strict=False):
            assert prev_end == next_start


class TestBatchSplit:
    def test_thscodes_batch_under_limit(self) -> None:
        thscodes = tuple(f"{i:06d}.SH" for i in range(50))
        batches = split_thscodes_batch(thscodes)
        assert batches == (thscodes,)

    def test_thscodes_batch_over_limit_splits(self) -> None:
        thscodes = tuple(f"{i:06d}.SH" for i in range(250))
        batches = split_thscodes_batch(thscodes)
        assert len(batches) == 3
        assert [len(b) for b in batches] == [100, 100, 50]


class TestFrequencyBlocking:
    def test_frequency_1d_supported(self) -> None:
        assert "1d" in THS_SUPPORTED_INTERVALS

    def test_minute_frequency_unsupported(self) -> None:
        """AC-14：分钟频 UNSUPPORTED，不伪造。"""
        for frequency in ("5min", "30min", "1h"):
            assert frequency not in THS_SUPPORTED_INTERVALS
        contract = THS_PROVIDER_CONTRACT_REGISTRY.contract_for(
            provider="ths", route_id="ths-stock-primary-v1"
        )
        with pytest.raises(ProviderContractError):
            contract.assert_request_matches(_request(frequency="5min"))


class TestHistoricalRequestTransform:
    def test_historical_request_transform(self) -> None:
        """历史 K 线请求变换：thscode/interval/start/end 毫秒戳闭区间 + adjust。"""
        request = _request(adjustment="qfq")
        kwargs = prepare_ths_historical_request(
            THS_PROVIDER_CONTRACT_REGISTRY.contract_for(
                provider="ths", route_id="ths-stock-primary-v1"
            ),
            request,
        )
        assert kwargs["thscode"] == "600519.SH"
        assert kwargs["interval"] == "1d"
        assert kwargs["adjust"] == "forward"
        assert isinstance(kwargs["start"], int)
        assert isinstance(kwargs["end"], int)

    def test_historical_request_window_shifts_by_shanghai_offset(self) -> None:
        """THS date_ms 是交易日上海零点：查询窗口相对中台 UTC 窗口 -8 小时。

        中台窗口 [2026-01-02 00:00 UTC, 2026-01-04 00:00 UTC) 要取交易日
        2026-01-02/01-03 的 bar（date_ms = 各日上海零点 = UTC 前一日 16:00），
        故 THS start = 2026-01-01 16:00 UTC，end = 2026-01-03 15:59:59.999 UTC。
        """
        request = _request()  # start 2026-01-02, end 2026-01-04
        kwargs = prepare_ths_historical_request(
            THS_PROVIDER_CONTRACT_REGISTRY.contract_for(
                provider="ths", route_id="ths-stock-primary-v1"
            ),
            request,
        )
        expected_start = int(datetime(2026, 1, 1, 16, 0, tzinfo=UTC).timestamp() * 1000)
        expected_end = int(
            (datetime(2026, 1, 3, 16, 0, tzinfo=UTC) - timedelta(milliseconds=1)).timestamp() * 1000
        )
        assert kwargs["start"] == expected_start
        assert kwargs["end"] == expected_end


class TestReferenceNormalization:
    def test_financials_null_transparent_and_meta_preserved(self) -> None:
        """AC-11：财务 period/fiscal_period 多期，null 透传不补零。"""
        envelope = ThsEnvelope(
            code=0,
            message="success",
            request_id="r1",
            data_item=(
                {
                    "thscode": "600519.SH",
                    "ticker": "600519",
                    "period": "annual",
                    "fiscal_year": 2025,
                    "fiscal_period": "Q4",
                    "report_date_ms": 1716105600000,
                    "period_end_ms": 1716105600000,
                    "currency": "CNY",
                    "basic_eps": None,
                    "revenue": 1.23,
                },
            ),
            data_timestamp_ms=None,
            raw={},
        )
        rows = normalize_financials(envelope)
        assert len(rows) == 1
        assert rows[0]["period"] == "annual"
        assert rows[0]["fiscal_period"] == "Q4"
        assert rows[0]["basic_eps"] is None  # null 透传不补零
        assert rows[0]["revenue"] == 1.23

    def test_financials_request_modes(self) -> None:
        """财务请求：区间与 limit 互斥，半开区间拒绝（AC-06 相关）。"""
        assert build_financials_request(thscode="600519.SH", limit=4)["limit"] == 4
        assert build_financials_request(thscode="600519.SH", start_ms=1, end_ms=2)["start"] == 1
        with pytest.raises(ThsReferenceError):
            build_financials_request(thscode="600519.SH", start_ms=1)
        with pytest.raises(ThsReferenceError):
            build_financials_request(thscode="600519.SH", start_ms=1, end_ms=2, limit=4)

    def test_adjustment_factors_request(self) -> None:
        """除复权请求：thscode 必填，from/to 可选。"""
        assert build_adjustment_factors_request(thscode="600519.SH")["thscode"] == "600519.SH"
        params = build_adjustment_factors_request(
            thscode="600519.SH", from_date="2024-01-01", to_date="2025-01-01"
        )
        assert params["from"] == "2024-01-01"
        assert params["to"] == "2025-01-01"
        with pytest.raises(ThsReferenceError):
            build_adjustment_factors_request(thscode="")

    def test_adjustment_factors_descending_by_ex_date(self) -> None:
        """AC-12：除复权事件按 ex_date_ms 降序。"""
        envelope = ThsEnvelope(
            code=0,
            message="success",
            request_id="r1",
            data_item=(
                {
                    "ticker": "600519",
                    "ex_date_ms": 1000,
                    "dividend_per_share": 1.0,
                    "per_share_bonus": 0,
                },
                {
                    "ticker": "600519",
                    "ex_date_ms": 3000,
                    "dividend_per_share": 0,
                    "per_share_bonus": 10,
                },
                {
                    "ticker": "600519",
                    "ex_date_ms": 2000,
                    "dividend_per_share": 2.0,
                    "per_share_bonus": 0,
                },
            ),
            data_timestamp_ms=None,
            raw={},
        )
        rows = normalize_adjustment_factors(envelope)
        assert [r["ex_date_ms"] for r in rows] == [3000, 2000, 1000]

    def test_calendar_double_field(self) -> None:
        """AC-12 相关：交易日历 date_ms + date 双字段。"""
        envelope = ThsEnvelope(
            code=0,
            message="success",
            request_id="r1",
            data_item=(
                {"date_ms": 1716105600000, "date": "20240520"},
                {"date_ms": 1716192000000, "date": "20240521"},
            ),
            data_timestamp_ms=None,
            raw={},
        )
        rows = normalize_calendar(envelope)
        assert [r["date"] for r in rows] == ["20240520", "20240521"]
        assert rows[0]["date_ms"] == 1716105600000

    def test_ticker_search_requires_q_and_thscode(self) -> None:
        """AC-13：标的检索 q 必填，thscode 完整。"""
        with pytest.raises(ThsReferenceError):
            build_tickers_search_request(q="")
        params = build_tickers_search_request(q="茅台", limit=50)
        assert params["q"] == "茅台"
        assert params["limit"] == 50

    def test_normalize_tickers_requires_thscode(self) -> None:
        envelope = ThsEnvelope(
            code=0,
            message="success",
            request_id="r1",
            data_item=(
                {
                    "thscode": "600519.SH",
                    "ticker": "600519",
                    "name": "贵州茅台",
                    "asset_type": "a-share",
                },
            ),
            data_timestamp_ms=None,
            raw={},
        )
        rows = normalize_tickers(envelope)
        assert rows[0]["thscode"] == "600519.SH"
        assert rows[0]["name"] == "贵州茅台"

    def test_tickers_list_limit_bounds(self) -> None:
        assert build_tickers_list_request(limit=1000)["limit"] == 1000
        with pytest.raises(ThsReferenceError):
            build_tickers_list_request(limit=20000)
