from collections import UserDict
from types import ModuleType

import pandas as pd
import pytest

from app.services.market_instrument import MarketInstrumentService, _first_present


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_name", [123, ""])
async def test_warehouse_lookup_uses_symbol_for_invalid_snapshot_name(snapshot_name):
    class InvalidNameService(MarketInstrumentService):
        async def _fetch_one(self, *_args, **_kwargs):
            return None

        async def _fetch_rows(self, *_args, **_kwargs):
            return []

        def _snapshot_from_latest_history(self, symbol, _rows):
            return {"name": snapshot_name, "symbol": symbol}

    payload = await InvalidNameService()._lookup_bond_warehouse(
        symbol="sh113527",
        start_date="2026-06-01",
        end_date="2026-06-19",
        period="daily",
        market="CN",
        warnings=[],
    )

    assert payload["name"] == "113527"


def test_first_present_reads_string_keys_from_a_hashable_key_mapping():
    row = UserDict({1: "not a candidate", "price": 1.25, "close": 1.2})

    assert _first_present(row, "close", "price") == 1.2


def test_fx_lookup_reads_selected_fields_from_a_pandas_row(monkeypatch):
    akshare = ModuleType("akshare")
    akshare.forex_spot_em = lambda: pd.DataFrame(
        [
            {
                "代码": "EURUSD",
                "名称": "欧元/美元",
                "最新价": 1.08,
                "price": 9.99,
                "涨跌额": 0.01,
            }
        ]
    )
    akshare.forex_hist_em = lambda **_kwargs: pd.DataFrame()
    monkeypatch.setitem(__import__("sys").modules, "akshare", akshare)

    payload = MarketInstrumentService()._lookup_fx(
        symbol="EURUSD",
        start_date="2026-06-01",
        end_date="2026-06-19",
        period="daily",
        market="FX",
        warnings=[],
    )

    assert payload["snapshot"]["price"] == 1.08
    assert payload["snapshot"]["change"] == 0.01
    assert payload["name"] == "欧元/美元"


def test_indicators_ignore_missing_values_and_keep_volume_average_without_close():
    service = MarketInstrumentService()

    with_closes = service._build_indicators(
        [
            {"close": None, "volume": 10},
            {"close": 100, "volume": 20},
            {"close": 101, "volume": None},
        ]
    )
    assert with_closes["latest_close"] == 101.0
    assert with_closes["return_pct"] == pytest.approx(1.0)
    assert with_closes["avg_volume"] == 15.0
    assert with_closes["observation_count"] == 2

    without_closes = service._build_indicators(
        [{"close": None, "volume": 10}, {"close": "invalid", "volume": 20}]
    )
    assert without_closes["latest_close"] is None
    assert without_closes["avg_volume"] == 15.0
    assert without_closes["observation_count"] == 2
