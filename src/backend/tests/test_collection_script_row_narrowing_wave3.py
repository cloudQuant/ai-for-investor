"""Shape pins for the iteration-204 collection-plane wave-3 row/value narrowing.

Every change in `fix/afi-collection-row-narrowing-2` is grounded in one of four kinds of
evidence, and each section below re-proves the claim the sites relied on:

* the None-branch ternaries (`to_numeric/to_datetime(x) if x is not None else NaN/NaT`) are
  only legal because the pinned pandas still coerces `None` to NaN/NaT - test 1 pins that
  library contract, and the per-site tests exercise the None path through the real methods;
* the `bool(...)` wraps around `save_data()` align the runtime with the `-> bool` docstring
  contract (siblings like fund_rating_sh.py already did `return bool(saved_rows)`), and every
  in-tree consumer reads it through `if success:` truthiness - the tests pin True/False
  *identity*, not truthiness, so a future edit that leaks the row count goes red;
* the three zero-arg `get_latest_date` overrides were dead code (their only references were
  commented out; ten sibling caixin files already keep the same body commented) and are now
  `_get_latest_trade_date`, so the inherited `MysqlBase.get_latest_date` stays callable with
  its documented signature;
* the rest is annotation/cast-only (`cast(int, ...)` on `SELECT COUNT(*)`, `dict[str, str]`
  params, kwargs value types) - those are pinned by source censuses because they cannot
  change runtime at all.

A false narrowing is worse than the mypy error it removes, so where the shape is claimed by
a DDL or a sibling contract, the test reproduces the evidence path, not just the outcome.
"""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Final, get_type_hints

import pytest

pd = pytest.importorskip("pandas", reason="optional pandas package is required for coercion probes")
pytest.importorskip("akshare", reason="optional akshare provider package is required")
pytest.importorskip("mysql.connector", reason="optional MySQL connector package is required")

SCRIPT_ROOT: Final = Path(__file__).resolve().parents[1] / "app" / "data_fetch" / "scripts"

PRECLOSE_SITES: Final = [
    "stocks/weekly/stock_hk_hist.py",
    "stocks/daily/stock_zh_a_hist.py",
    "stocks/daily/stock_board_industry_hist_em.py",
    "stocks/daily/stock_board_concept_hist_em.py",
    "indexs/weekly/index_global_hist_em.py",
    "indexs/daily/index_zh_a_hist.py",
    "futures/daily/futures_hist_em.py",
    "funds/weekly/reits_hist_em.py",
    "funds/daily/fund_lof_hist_em.py",
    "common/daily/forex_hist_em.py",
]


def _source(rel: str) -> str:
    return (SCRIPT_ROOT / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. the library contract every None-branch ternary stands on
# ---------------------------------------------------------------------------


def test_pinned_pandas_still_coerces_none_to_nan_and_nat() -> None:
    """The None branches replaced `to_numeric(None/to_datetime(None))`, whose values are pinned here.

    If a future pandas made these raise (or return something that is not NaN/NaT), every
    `... if raw is not None else float("nan") / pd.NaT` in this wave would be a behavior
    change, and this test must go red first.
    """
    nan_value = pd.to_numeric(None, errors="coerce")
    assert pd.isna(nan_value)
    parsed = pd.to_datetime(None, format="%Y%m%d", errors="coerce")
    assert pd.isna(parsed)
    # float("nan") through to_numeric stays NaN, exactly like the None call it replaces.
    assert pd.isna(pd.to_numeric(float("nan"), errors="coerce"))


def test_series_get_returns_none_for_missing_labels() -> None:
    """`Series.get` (DataFrame.get on columns) hands None, never raises - the absent-column
    premise of the gpzy / futures_hold_pos / currency_fallback None branches."""
    frame = pd.DataFrame({"ORG_NUM": [1]})
    assert frame.get("WARNING_STATE_1_RATE") is None
    assert frame["ORG_NUM"].get("no-such-label") is None


# ---------------------------------------------------------------------------
# 2. the ten Eastmoney `preClose` reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", PRECLOSE_SITES)
def test_preclose_read_is_none_guarded_not_direct(rel: str) -> None:
    """No site may revert to `pd.to_numeric(data.get('preClose'), ...)` (the `Any | None` the
    plane reported) nor to a value-changing default: the guarded form is the one whose None
    branch provably equals the old coerced NaN."""
    source = _source(rel)
    assert 'pd.to_numeric(data.get("preClose"), errors="coerce")' not in source
    assert 'raw_pre_close = data.get("preClose")' in source
    assert "if raw_pre_close is not None" in source
    assert 'else float("nan")' in source


def test_preclose_site_count_is_exactly_ten() -> None:
    """The census the wave measured against: exactly the ten files above read `preClose`."""
    found = [
        str(p.relative_to(SCRIPT_ROOT))
        for p in SCRIPT_ROOT.rglob("*.py")
        if 'data.get("preClose")' in p.read_text(encoding="utf-8")
    ]
    assert sorted(found) == sorted(PRECLOSE_SITES)


# ---------------------------------------------------------------------------
# 3. dict_result / kwargs date sites: None keeps the old falsy-parsed outcome
# ---------------------------------------------------------------------------


def test_flatten_dict_result_none_data_date_matches_old_coercion() -> None:
    from app.data_fetch.scripts.common.dict_result import flatten_dict_result

    frame = flatten_dict_result(pd.DataFrame({"symbol": ["000001"]}), data_date=None)
    assert frame["data_date"].iloc[0] == pd.Timestamp.now().date()

    parsed = flatten_dict_result(pd.DataFrame({"symbol": ["000001"]}), data_date="20240105")
    assert parsed["data_date"].iloc[0] == date(2024, 1, 5)

    bad = flatten_dict_result(pd.DataFrame({"symbol": ["000001"]}), data_date="not-a-date")
    assert bad["data_date"].iloc[0] == pd.Timestamp.now().date()


@pytest.mark.parametrize(
    ("rel", "lookup"),
    [
        ("stocks/daily/stock_sse_deal_daily.py", 'date_arg = kwargs.get("date")'),
        ("funds/weekly/option_hist_shfe.py", 'date_arg = kwargs.get("trade_date")'),
        ("funds/weekly/option_hist_czce.py", 'date_arg = kwargs.get("trade_date")'),
    ],
)
def test_kwargs_date_reads_guard_none(rel: str, lookup: str) -> None:
    source = _source(rel)
    assert lookup in source
    assert "pd.NaT\n                    if date_arg is None" in source
    assert 'else pd.to_datetime(date_arg, format="%Y%m%d", errors="coerce")' in source
    assert 'pd.to_datetime(kwargs.get("date")' not in source
    assert 'pd.to_datetime(kwargs.get("trade_date")' not in source


# ---------------------------------------------------------------------------
# 4. jin10 `_date_before` guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-01-05", "2024-01-04"),
        (date(2024, 1, 5), "2024-01-04"),
        (None, None),
        (Decimal("1"), None),
        (b"20240105", None),
        (True, None),
        (pd.NaT, None),
    ],
)
def test_jin10_date_before_guard_reproduces_the_old_coercion(
    value: object, expected: str | None
) -> None:
    """For every scalar that is not str/int/float/date, the old call produced NaT (probed on the
    pinned pandas) and this function returned None; the isinstance guard short-circuits to the
    same None. Strings and dates must still parse exactly as before."""
    from app.data_fetch.scripts.common.daily._jin10_macro import _date_before

    assert _date_before(value) == expected


def test_jin10_date_before_still_parses_numbers() -> None:
    """int/float were never rejected by the guard - they still go through to_datetime's epoch
    semantics, so a numeric first column keeps its (odd but real) old answer."""
    import datetime as _dt

    from app.data_fetch.scripts.common.daily._jin10_macro import _date_before

    expected = (
        pd.to_datetime(1700000000.0, errors="coerce").date() - _dt.timedelta(days=1)
    ).isoformat()
    assert _date_before(1700000000.0) == expected
    assert _date_before(1700000000) == expected


# ---------------------------------------------------------------------------
# 5. gpzy / futures_hold_pos / currency_fallback column reads
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("stock_gpzy_distribute_statistics_company_em", "StockGpzyDistributeStatisticsCompanyEm"),
        ("stock_gpzy_distribute_statistics_bank_em", "StockGpzyDistributeStatisticsBankEm"),
    ],
)
def test_gpzy_missing_numeric_columns_broadcast_nan(module_name: str, class_name: str) -> None:
    """The old `to_numeric(df.get(col))` fed None (absent column) to the coercion and broadcast
    the resulting NaN scalar into the frame; the guarded None branch must produce the same
    all-NaN column, not raise and not skip the column."""
    module = pytest.importorskip(f"app.data_fetch.scripts.stocks.daily.{module_name}")
    normalize = getattr(module, class_name).normalize_columns
    frame = pd.DataFrame(
        {
            "PFORG_CODE": [1001, 1002],
            "SECURITY_NAME_ABBR": ["甲公司", "乙公司"],
            "PFORG_TYPE": ["券商", "银行"],
            "ORG_NUM": [3, 4],
        }
    )
    result = normalize(frame)
    assert result["org_num"].tolist() == [3, 4]
    for col in ("warning_state_1_rate", "warning_state_3", "pledge_num"):
        assert col in result.columns, col
        assert result[col].isna().all(), col


def test_futures_hold_pos_missing_rank_columns_become_nan() -> None:
    from app.data_fetch.scripts.futures.daily.futures_hold_pos_sina import FuturesHoldPosSina

    frame = pd.DataFrame({"会员简称": ["A期货", "B期货"], "净持仓": [10, -3]})
    result = FuturesHoldPosSina.normalize_columns(frame, contract="cu2609", rank_type="前20会员")
    assert result["rank_num"].isna().all()
    assert result["change_value"].isna().all()
    assert result["member_name"].tolist() == ["A期货", "B期货"]
    assert result["rank_value"].tolist() == [10, -3]

    present = pd.DataFrame(
        {"名次": [1, 2], "会员简称": ["A", "B"], "比上交易增减": [5, -5], "成交量": [9, 8]}
    )
    result2 = FuturesHoldPosSina.normalize_columns(present, contract="cu2609", rank_type="前20会员")
    assert result2["rank_num"].tolist() == [1, 2]
    assert result2["change_value"].tolist() == [5, -5]


def test_currency_boc_rates_row_skips_missing_cells() -> None:
    from app.data_fetch.scripts.common.currency_fallback import _boc_rates_for_row

    assert _boc_rates_for_row(pd.Series(dtype=object)) == {"CNY": 1.0}
    row = pd.Series({"美元": "7.10", "欧元": None})
    rates = _boc_rates_for_row(row)
    assert rates["CNY"] == 1.0
    # USD is a SAFE_DIRECT_CODES member: value/100. The None 欧元 cell takes the guarded branch
    # (NaN) and is skipped by the pre-existing `pd.isna(value)` guard, exactly like the old call.
    assert rates["USD"] == pytest.approx(0.071)
    assert "EUR" not in rates


# ---------------------------------------------------------------------------
# 6. the eight save_* functions now hand back the bool their docstring promises
# ---------------------------------------------------------------------------

SAVE_BOOL_SITES: Final = [
    ("open_fund_rank_em", "OpenFundRankEm", "save_fund_rank_data"),
    ("fund_value_estimation_em", "FundValueEstimationEm", "save_estimation_data"),
    ("fund_money_rank_em", "FundMoneyRankEm", "save_money_rank_data"),
    ("fund_lcx_rank_em", "FundLcxRankEm", "save_lcx_rank_data"),
    ("fund_individual_analysis_xq", "FundAnalysisXq", "save_analysis_data"),
    ("fund_hk_rank_em", "FundHkRankEm", "save_hk_rank_data"),
    ("fund_exchange_rank_em", "FundExchangeRankEm", "save_exchange_rank_data"),
    ("fund_achivement_xq", "FundAchievementXq", "save_achievement_data"),
]


@pytest.mark.parametrize(("module_name", "class_name", "method"), SAVE_BOOL_SITES)
@pytest.mark.parametrize("saved", [200, 0, False])
def test_save_functions_return_declared_bool_identity(
    module_name: str, class_name: str, method: str, saved: object
) -> None:
    """save_data() is `int | Literal[False]` (core/mysql_base.py); the docstring contract of
    these eight is bool and every consumer uses `if success:` truthiness. The wave made the
    runtime match the contract with `bool(...)`, keeping every truthy decision identical
    (200 -> True, 0 -> False, False -> False) - asserted here by identity, so the leaked row
    count cannot come back."""
    module = pytest.importorskip(f"app.data_fetch.scripts.funds.weekly.{module_name}")
    cls = getattr(module, class_name)
    service = object.__new__(cls)
    service.logger = SimpleNamespace(warning=lambda *a, **k: None, info=lambda *a, **k: None)
    service.table_name = "WHATEVER"
    service._get_existing_ids = lambda: set()
    captured: list = []

    def fake_save_data(**kwargs: object) -> object:
        captured.append(kwargs)
        return saved

    service.save_data = fake_save_data
    frame = pd.DataFrame({"R_ID": ["a", "b"]})

    result = getattr(service, method)(frame)

    assert result is (bool(saved))
    assert captured, "save_data was still never reached"


def test_fund_types_param_accepts_none() -> None:
    from app.data_fetch.scripts.funds.weekly.open_fund_rank_em import OpenFundRankEm

    hints = get_type_hints(OpenFundRankEm.run)
    assert hints["fund_types"] is not None
    assert "NoneType" in str(hints["fund_types"]) or "None" in str(hints["fund_types"])


# ---------------------------------------------------------------------------
# 7. fund_rating_sh parser contracts
# ---------------------------------------------------------------------------


def test_fund_rating_sh_parsers_return_what_the_body_actually_produces() -> None:
    from app.data_fetch.scripts.funds.weekly.fund_rating_sh import FundRatingSh

    service = object.__new__(FundRatingSh)
    assert service.parse_fee_rate("0.15%") == pytest.approx(0.0015)
    assert service.parse_fee_rate("") is None
    assert service.parse_fee_rate("abc%") is None
    assert service.parse_date("2023-06-30") == date(2023, 6, 30)
    assert service.parse_date(date(2020, 1, 2)) == date(2020, 1, 2)
    assert service.parse_date("nope") is None

    hints = get_type_hints(FundRatingSh.parse_fee_rate)
    assert hints["return"] == float | None
    hints_date = get_type_hints(FundRatingSh.parse_date)
    assert hints_date["return"] == date | None


# ---------------------------------------------------------------------------
# 8. the dead zero-arg get_latest_date overrides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("caixin_spillover_index", "CaixinSpilloverIndex"),
        ("caixin_basic_index", "CaixinBasicIndex"),
        ("a_share_news_sentiment_index", "AShareNewsSentimentIndex"),
    ],
)
def test_latest_trade_date_no_longer_shadows_the_base(module_name: str, class_name: str) -> None:
    """The three classes kept a zero-arg `get_latest_date` that no live code called (its only
    references were commented out, and ten sibling caixin files keep the same body commented).
    It made every *documented* `MysqlBase.get_latest_date(table_name, ...)` call on the instance
    a TypeError. After the rename the base signature is inherited whole."""
    from app.data_fetch.core.mysql_base import MysqlBase

    module = pytest.importorskip(f"app.data_fetch.scripts.indexs.weekly.{module_name}")
    cls = getattr(module, class_name)

    assert cls.get_latest_date.__qualname__.startswith("MysqlBase.")
    assert cls.get_latest_date is MysqlBase.get_latest_date
    assert hasattr(cls, "_get_latest_trade_date")

    executed: list[str] = []
    service = object.__new__(cls)
    service.logger = SimpleNamespace(warning=lambda *a, **k: None)
    service.table_name = "WHATEVER"

    class _Result:
        def __init__(self, value: object) -> None:
            self._value = value

        def __bool__(self) -> bool:
            return self._value is not None

        def __getitem__(self, index: int) -> object:
            return self._value

    service.execute_sql = lambda sql, fetch_one=False: executed.append(sql) or _Result(
        date(2026, 11, 6)
    )
    assert service._get_latest_trade_date() == date(2026, 11, 6)
    assert "MAX(TRADE_DATE)" in executed[0]


# ---------------------------------------------------------------------------
# 9. annotation / cast-only sites, pinned by census
# ---------------------------------------------------------------------------


def test_eastmoney_request_param_type_matches_both_callers() -> None:
    from app.data_fetch.scripts.stocks.daily.stock_hsgt_hold_stock_em import StockHsgtHoldStockEm

    hints = get_type_hints(StockHsgtHoldStockEm._request_eastmoney)
    assert hints["params"] == dict[str, str]

    captured: dict = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"code": 0, "result": {"data": []}}

    def fake_get(url: str, params: dict, headers: dict, timeout: int) -> _Response:
        captured["params"] = params
        return _Response()

    import app.data_fetch.scripts.stocks.daily.stock_hsgt_hold_stock_em as mod

    original = mod.requests.get
    mod.requests.get = fake_get
    try:
        service = object.__new__(StockHsgtHoldStockEm)
        service.logger = SimpleNamespace(warning=lambda *a, **k: None)
        out = service._request_eastmoney({"pageSize": "1", "pageNumber": "1"})
        assert out == {"code": 0, "result": {"data": []}}
        assert captured["params"] == {"pageSize": "1", "pageNumber": "1"}
    finally:
        mod.requests.get = original


def test_hsgt_agg_map_mixed_values_stay_mixed() -> None:
    """`agg_map` is built with one callable then filled with "first"; the wave annotated the
    dict instead of coercing the values, so the runtime payloads are unchanged."""
    source = _source("stocks/daily/stock_hsgt_hold_stock_em.py")
    assert "agg_map: dict[str, str | Callable[[pd.Series[Any]], str | None]]" in source
    assert 'agg_map[col] = "first"' in source


def test_count_and_seq_index_casts_are_the_established_cast_shape() -> None:
    """`cast(int, ...)` over a connector row is the precedent this repo already set in
    common/monthly/trading_days.py (SELECT COUNT(*) -> BIGINT -> int). SHOW INDEX column 4 is
    Seq_in_index, likewise an integer. Both casts are compile-time identity."""
    trading = _source("common/monthly/trading_days.py")
    assert "cast(int, result[0])" in trading

    cninfo = _source("stocks/weekly/stock_industry_pe_ratio_cninfo.py")
    assert "row_count = int(cast(int, (self.require_cursor().fetchone() or [0])[0]) or 0)" in cninfo

    futures = _source("futures/weekly/daily_market_data.py")
    assert "key=lambda item: cast(int, item[3])" in futures

    zh_hist = _source("indexs/daily/index_zh_a_hist.py")
    assert 'pd.to_datetime(cast(date, row[0]), errors="coerce")' in zh_hist


@pytest.mark.parametrize(
    ("rel", "needle"),
    [
        (
            "futures/weekly/daily_market_data.py",
            'kwargs: dict[str, str | int] = {"symbol": symbol}',
        ),
        ("funds/hourly/option_sse_minute_sina.py", "kwargs: dict[str, str | int] = {"),
    ],
)
def test_mixed_kwargs_dicts_are_typed_from_their_own_writes(rel: str, needle: str) -> None:
    """symbol iterates an all-str constant and `_call_timeout`/`call_timeout` is only inserted
    under a non-None `int` guard, so `dict[str, str | int]` is the value type the code itself
    writes - not an Any blanket."""
    assert needle in _source(rel)


def test_index_assignment_wraps_with_datetimeindex() -> None:
    """`df.index = series` coerces to the same DatetimeIndex that `df.index =
    pd.DatetimeIndex(series)` assigns (probed on the pinned pandas; equal type, values and
    name), and only the Index arm satisfies the stubs."""
    series = pd.to_datetime(pd.Series(["2024-01-01", "bad"]), errors="coerce")
    a = pd.DataFrame({"x": [1, 2]})
    a.index = series
    b = pd.DataFrame({"x": [1, 2]})
    b.index = pd.DatetimeIndex(series)
    assert type(a.index) is type(b.index) is pd.DatetimeIndex
    assert a.index.equals(b.index)
    assert a.index.name == b.index.name

    source = _source("indexs/daily/index_zh_a_hist_min_em.py")
    assert 'df.index = pd.DatetimeIndex(pd.to_datetime(df["时间"], errors="coerce"))' in source


def test_nbs_preset_lookup_guard_matches_the_old_miss() -> None:
    from app.data_fetch.scripts.common.daily.macro_china_nbs_nation import _normalise_queries

    presets = _normalise_queries({})
    assert len(presets) == 2
    assert {p["kind"] for p in presets} == {"年度数据"}

    merged = _normalise_queries({"kind": "年度数据", "path": "人口 > 总人口"})
    assert len(merged) == 1
    assert merged[0]["cid"], "the str/str lookup must still hit the preset"

    non_str = _normalise_queries({"kind": ["年度数据"], "path": None})
    assert non_str == [{"kind": ["年度数据"], "path": None}], (
        "a non-str kind/path pair was never a preset key; the guard must return the query "
        "unchanged like the old mapping miss did"
    )

    query_list = _normalise_queries(
        {"queries": [{"kind": "年度数据", "path": "人口 > 总人口", "period": "X"}]}
    )
    assert query_list[0]["period"] == "X"
    assert "cid" in query_list[0]

    list_miss = _normalise_queries({"queries": [{"kind": 5, "path": 6}]})
    assert list_miss == [{"kind": 5, "path": 6}]

    # Documented crash-path difference (behavior probe, HEAD vs worktree): the old line fed an
    # unhashable pair straight into dict.get and TypeError escaped fetch_data. Such a pair can
    # never equal a preset key, so the guard now gives it the same guaranteed-miss passthrough
    # every hashable miss (the int case above) always had.
    unhashable = _normalise_queries({"queries": [{"kind": ["年度数据"], "path": 6}]})
    assert unhashable == [{"kind": ["年度数据"], "path": 6}]


def test_currency_connect_cast_and_loop_rename_present() -> None:
    """`mysql.connector.connect` returns MySQLConnection unless pool kwargs are passed, and
    DB_CONFIG only ever carries host/user/password/database/port - the cast states that; the
    renamed loop target cannot clash with the `**_: Any` catch-all again."""
    source = _source("common/currency_fallback.py")
    assert (
        "return cast(mysql.connector.MySQLConnection, mysql.connector.connect(**DB_CONFIG))"
        in source
    )
    assert "for _row_index, row in rows.iterrows():" in source

    head = Path(__file__).resolve().parents[1] / "app" / "data_fetch" / "configs" / "db_config.py"
    config_source = head.read_text(encoding="utf-8")
    assert "pool_name" not in config_source


def test_no_type_ignore_was_added_anywhere_in_the_wave() -> None:
    """Owner ruling: ignores are not a victory. None of the wave-3 files may carry one."""
    touched = (
        PRECLOSE_SITES
        + [
            "common/dict_result.py",
            "common/currency_fallback.py",
            "common/daily/_sina_macro.py",
            "common/daily/_jin10_macro.py",
            "common/daily/macro_china_nbs_nation.py",
            "common/daily/forex_hist_em.py",
            "stocks/daily/stock_sse_deal_daily.py",
            "stocks/daily/stock_hsgt_hold_stock_em.py",
            "stocks/daily/stock_gpzy_distribute_statistics_company_em.py",
            "stocks/daily/stock_gpzy_distribute_statistics_bank_em.py",
            "stocks/weekly/stock_industry_pe_ratio_cninfo.py",
            "indexs/daily/index_zh_a_hist.py",
            "indexs/daily/index_zh_a_hist_min_em.py",
            "indexs/weekly/caixin_spillover_index.py",
            "indexs/weekly/caixin_basic_index.py",
            "indexs/weekly/a_share_news_sentiment_index.py",
            "futures/daily/futures_hold_pos_sina.py",
            "futures/weekly/daily_market_data.py",
            "funds/hourly/option_sse_minute_sina.py",
            "funds/weekly/option_hist_shfe.py",
            "funds/weekly/option_hist_czce.py",
        ]
        + [f"funds/weekly/{name}.py" for name, _cls, _m in SAVE_BOOL_SITES]
    )
    offenders = [rel for rel in touched if "# type: ignore" in _source(rel)]
    assert offenders == []


def test_sina_extract_records_walks_json_as_any() -> None:
    """The data_path walk descends into a demjson tree, so the node really can be any JSON
    value; the annotation records that instead of pretending it is a dict (the old `return
    dict | list` contradiction)."""
    source = _source("common/daily/_sina_macro.py")
    assert "data: Any = data_json" in source
    tree = ast.parse(source)
    annotated = [
        n.target.id
        for n in ast.walk(tree)
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    ]
    assert "data" in annotated
