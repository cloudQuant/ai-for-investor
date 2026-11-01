"""FX pair history is derived from the CNY mid-rate reference table.

CURRENCY_BOC_SAFE stores 人民币 per 100 foreign units for one date, so a pair's rate is the
quotient of its two legs. Two properties are pinned here: the derivation must not collapse a
pair onto a single currency column (the defect that wrote USDCNH=685 into the history cache),
and the reference series must not pretend to carry an intraday range.
"""

from __future__ import annotations

import pytest

from app.services.market_instrument import MarketInstrumentService
from app.services.market_instrument_asset_adapter import (
    _fx_history_from_boc_safe,
    _fx_pair_legs,
)

SAFE_ROWS = [
    {"日期": "2026-07-02", "美元": 680.88, "欧元": 773.62, "日元": 4.184},
    {"日期": "2026-07-03", "美元": 680.47, "欧元": 776.09, "日元": 4.2094},
]


def _install_warehouse(monkeypatch, rows=SAFE_ROWS):
    captured: dict[str, object] = {}

    async def fake_fetch_rows(_self, sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return list(rows)

    monkeypatch.setattr(MarketInstrumentService, "_fetch_rows", fake_fetch_rows)
    return captured


@pytest.mark.parametrize(
    "code, expected",
    [
        ("USDCNH", ("USD", "CNH")),
        ("EURUSD", ("EUR", "USD")),
        ("AUDCNYC", ("AUD", "CNY")),
        ("CNYAEDC", ("CNY", "AED")),
    ],
)
def test_pair_codes_split_into_two_legs(code, expected):
    assert _fx_pair_legs(code) == expected


@pytest.mark.parametrize("code", ["USD", "TOOLONGCODE", "EURUS"])
def test_unsplittable_codes_are_refused(code):
    assert _fx_pair_legs(code) is None


async def test_cny_pair_divides_the_mid_rate_by_100(monkeypatch):
    captured = _install_warehouse(monkeypatch)
    warnings: list[str] = []

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="USDCNH",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=warnings,
    )

    assert [row["close"] for row in rows] == [6.8088, 6.8047]
    # The offshore leg is an approximation and must be disclosed, not silently folded in.
    assert any("CNH" in warning for warning in warnings)
    assert captured["params"] == {"start": "2026-07-01", "end": "2026-07-03"}


async def test_cross_pair_divides_one_leg_by_the_other(monkeypatch):
    _install_warehouse(monkeypatch)

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="EURUSD",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=[],
    )

    assert rows[1]["close"] == pytest.approx(776.09 / 680.47)
    assert rows[0]["close"] == pytest.approx(773.62 / 680.88)


async def test_reverse_quoted_pair_uses_the_reciprocal_legs(monkeypatch):
    _install_warehouse(monkeypatch)

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="USDJPY",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=[],
    )

    assert rows[1]["close"] == pytest.approx(680.47 / 4.2094)


async def test_reference_series_does_not_invent_an_intraday_range(monkeypatch):
    _install_warehouse(monkeypatch)

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="USDCNH",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=[],
    )

    last = rows[-1]
    assert last["high"] == last["low"] == last["close"]
    assert last["open"] == rows[0]["close"]


async def test_duplicate_import_copies_collapse_to_one_point_per_day(monkeypatch):
    _install_warehouse(
        monkeypatch,
        rows=[
            {"日期": "2026-07-03", "美元": 680.47, "欧元": 776.09, "日元": 4.2094},
            {"日期": "2026-07-03", "美元": 680.47, "欧元": 776.09, "日元": 4.2094},
        ],
    )

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="USDCNH",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=[],
    )

    assert len(rows) == 1


async def test_unquoted_currency_is_refused_with_a_warning(monkeypatch):
    _install_warehouse(monkeypatch)
    warnings: list[str] = []

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="USDINR",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=warnings,
    )

    assert rows == []
    assert any("INR" in warning for warning in warnings)


async def test_unparsable_symbol_is_refused_without_touching_the_warehouse(monkeypatch):
    captured = _install_warehouse(monkeypatch)
    warnings: list[str] = []

    rows = await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="XYZ",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=warnings,
    )

    assert rows == []
    assert warnings
    assert "sql" not in captured


async def test_window_query_groups_by_date_so_limit_counts_trading_days(monkeypatch):
    captured = _install_warehouse(monkeypatch)

    await _fx_history_from_boc_safe(
        MarketInstrumentService(),
        symbol="EURUSD",
        start_date="2026-07-01",
        end_date="2026-07-03",
        warnings=[],
    )

    assert "GROUP BY `日期`" in captured["sql"]
