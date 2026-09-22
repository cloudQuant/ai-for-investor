"""THS 全市场导出的 fixture 测试（AC-19/20 的确定性部分）。"""

from __future__ import annotations

import pytest

from app.services.market_data.ths_dump import (
    ThsDumpError,
    parse_download_url,
    ths_dump_spec,
)


class TestDumpSpec:
    def test_known_dump_ids_resolve(self) -> None:
        spec = ths_dump_spec("a_share_daily_k_1d_none_10y")
        assert spec.download_path == "/api/dump/market-dumps/daily-k/download-url"
        assert "thscode" in spec.parquet_columns
        assert "date_ms" in spec.parquet_columns

    def test_adjustment_dump_columns(self) -> None:
        spec = ths_dump_spec("a_share_adjustment_factors_event_none_all")
        assert "ex_date_ms" in spec.parquet_columns
        assert "dividend_per_share" in spec.parquet_columns

    def test_unknown_dump_rejected(self) -> None:
        with pytest.raises(ThsDumpError) as exc:
            ths_dump_spec("nonexistent_dump")
        assert exc.value.code == "THS_DUMP_UNREGISTERED"


class TestDownloadUrl:
    def test_parse_presigned_url(self) -> None:
        payload = {
            "code": 0,
            "data": {"presigned_url": "https://o.thsi.cn/x.parquet?Signature=abc"},
        }
        assert parse_download_url(payload) == "https://o.thsi.cn/x.parquet?Signature=abc"

    def test_missing_url_rejected(self) -> None:
        with pytest.raises(ThsDumpError) as exc:
            parse_download_url({"code": 0, "data": {}})
        assert exc.value.code == "THS_DUMP_URL_MISSING"
