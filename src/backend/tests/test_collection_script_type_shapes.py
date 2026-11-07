"""Shape censuses for the collection plane's mechanically-fixed error families.

`config/mypy_collection.ini` measures `app/data_fetch/scripts` (1057 scripts) today. Two of
the shapes it reported were not type noise but code that could only ever work by accident:

* one name bound first to a `set(...)` and then to a `list(...)` - mypy read the later
  slice/shuffle as subscripting a set (`index` / `assignment` / `call-overload`);
* `D.get(k) * 100 if D.get(k) is not None` - the guard tested a *second* call, so nothing
  narrowed the value that was multiplied (`operator`).

Both are now gone from the tree, and the counts are asserted to stay 0 rather than being
silenced with an ignore or a baseline. The last two tests pin the behaviour the fixes are
supposed to keep: volumes scale by 100 and stay absent-tolerant, and the weekly fund-rank
`parse_date()` returns a real `datetime.date` (its `datetime.date` annotation was a
reference to the `.date` *method*, valid only because PEP 563 keeps annotations unevaluated).

The second half of this file covers the families that needed a per-site decision: the honest
`_DatabaseRow` union (PR #275) makes every `row[0]` a `Decimal | bytes | date | ... | str | None`,
so `.lower()`, `> 0` and f-strings on it are reported (`operator` / `union-attr` /
`str-bytes-safe`). Each of those was narrowed against the column's own DDL, never with a blanket
accessor, and each narrowing has a test below that goes red if the claimed type is wrong.
"""

from __future__ import annotations

import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest

# The row-narrowing cases below drive real script classes, so they import code whose packages are
# optional installs (`pandas` ships in the `backtrader`/`data` extras, `akshare` in `data`, the
# connector is the MySQL driver). A missing one is an environment gap, not a product failure, so
# the file reports as skipped instead of erroring at collection - the discipline
# test_akshare_to_mysql_provider.py already applies to pymysql.
pd = pytest.importorskip("pandas", reason="optional pandas package is required")
pytest.importorskip("akshare", reason="optional akshare provider package is required")
pytest.importorskip("mysql.connector", reason="optional MySQL connector package is required")

SCRIPT_ROOT: Final = Path(__file__).resolve().parents[1] / "app" / "data_fetch" / "scripts"

#: `script = SomeScript()` census in test_collection_script_entry_points.py uses the same root.
SET_TO_LIST_SAMPLE: Final = (
    "def run(self, codes, max_codes):\n"
    "    codes_to_fetch = set(codes) - set()\n"
    "    codes_to_fetch = list(codes_to_fetch)\n"
    "    return codes_to_fetch[:max_codes]\n"
)

DOUBLE_GET_SAMPLE: Final = (
    "def fetch(data):\n"
    "    return {\n"
    '        "sell_5_vol": data.get("f32") * 100 if data.get("f32") is not None else None,\n'
    "    }\n"
)

#: `X(...) ... if X(...)`: the guard is a *second* call, so nothing narrows the object the body
#: dereferences. Same root cause as `DOUBLE_GET_SAMPLE`, different syntax (`union-attr`).
RECALLED_CALL_SAMPLE: Final = (
    "def build(symbol):\n"
    "    return re.match('([A-Z]+)', symbol).group(1) if re.match('([A-Z]+)', symbol) else ''\n"
)


def _set_list_rebindings(source: str) -> list[tuple[str, str]]:
    """Names bound to a `set(...)` and also to a `list(...)` inside the same function."""
    offenders: list[tuple[str, str]] = []
    for fn in (
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    ):
        constructors: dict[str, set[str]] = {}
        for node in ast.walk(fn):
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                continue
            name, value = node.targets[0].id, node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in ("set", "list")
            ):
                constructors.setdefault(name, set()).add(value.func.id)
            elif (
                isinstance(value, ast.BinOp)
                and isinstance(value.left, ast.Call)
                and isinstance(value.left.func, ast.Name)
            ):
                if value.left.func.id == "set":
                    constructors.setdefault(name, set()).add("set")
        offenders.extend(
            (fn.name, name) for name, kinds in constructors.items() if {"set", "list"} <= kinds
        )
    return offenders


def _double_get_guards(source: str) -> list[int]:
    """`D.get(k) ... if D.get(k) is <cmp>` lines: the guard cannot narrow the branch value."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare)):
            continue
        left = node.test.left
        if not (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Attribute)
            and left.func.attr == "get"
        ):
            continue
        if ast.unparse(left) in ast.unparse(node.body) or ast.unparse(left) in ast.unparse(
            node.orelse
        ):
            hits.append(node.lineno)
    return hits


def _scripts() -> list[Path]:
    return [p for p in sorted(SCRIPT_ROOT.rglob("*.py")) if p.name != "__init__.py"]


def _recalled_call_guards(source: str) -> list[int]:
    """`f(...) ... if f(...)` lines: the guard calls again, so it narrows nothing."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.IfExp) and isinstance(node.test, ast.Call)):
            continue
        test_src = ast.unparse(node.test)
        branches = f"{ast.unparse(node.body)} {ast.unparse(node.orelse)}"
        if test_src in branches and test_src != branches.strip():
            hits.append(node.lineno)
    return hits


def test_the_rebinding_census_finds_the_shape_it_is_meant_to_prevent() -> None:
    assert _set_list_rebindings(SET_TO_LIST_SAMPLE) == [("run", "codes_to_fetch")]


def test_the_double_get_census_finds_the_shape_it_is_meant_to_prevent() -> None:
    assert _double_get_guards(DOUBLE_GET_SAMPLE)


def test_the_recalled_call_census_finds_the_shape_it_is_meant_to_prevent() -> None:
    assert _recalled_call_guards(RECALLED_CALL_SAMPLE)


def test_no_script_rebinds_one_name_from_set_to_list() -> None:
    scripts = _scripts()
    assert len(scripts) == 1057, f"the census scope moved: {len(scripts)} scripts"
    offenders = [
        f"{p.relative_to(SCRIPT_ROOT.parent.parent)} {hits}"
        for p in scripts
        if (hits := _set_list_rebindings(p.read_text(encoding="utf-8")))
    ]
    assert not offenders, f"names rebound from set to list: {offenders[:10]}"


def test_no_script_narrows_a_second_get_call() -> None:
    offenders = [
        f"{p.relative_to(SCRIPT_ROOT.parent.parent)}:{line}"
        for p in _scripts()
        for line in _double_get_guards(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"double-call guards that never narrow: {offenders[:10]}"


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.mark.parametrize(
    ("payload", "expected_sell_5_vol", "expected_buy_5_vol"),
    [
        ({"f32": 300, "f12": 50}, 30000.0, 5000.0),
        ({"f32": 0, "f12": -5}, 0.0, -500.0),
        ({}, None, None),
    ],
)
def test_bid_ask_volumes_scale_by_100_and_tolerate_absence(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    expected_sell_5_vol: float | None,
    expected_buy_5_vol: float | None,
) -> None:
    from app.data_fetch.scripts.stocks.daily import stock_bid_ask_em

    monkeypatch.setattr(
        stock_bid_ask_em, "request_eastmoney", lambda *a, **k: _Response({"data": payload})
    )
    df = stock_bid_ask_em.StockBidAskEm.fetch_quote("000001")
    values = dict(zip(df["item"], df["value"], strict=True))

    for item, expected in (("sell_5_vol", expected_sell_5_vol), ("buy_5_vol", expected_buy_5_vol)):
        actual = values[item]
        if expected is None:
            assert actual is None or (isinstance(actual, float) and actual != actual), item
        else:
            assert float(actual) == expected, item


@pytest.mark.parametrize(
    "module_name",
    [
        "open_fund_rank_em",
        "fund_money_rank_em",
        "fund_lcx_rank_em",
        "fund_hk_rank_em",
        "fund_exchange_rank_em",
    ],
)
def test_weekly_fund_rank_parse_date_returns_a_real_date(module_name: str) -> None:
    module = pytest.importorskip(f"app.data_fetch.scripts.funds.weekly.{module_name}")
    cls = next(
        obj
        for name, obj in vars(module).items()
        if isinstance(obj, type) and name[0].isupper() and hasattr(obj, "parse_date")
    )
    parse_date = cls.parse_date
    stub = SimpleNamespace(logger=SimpleNamespace(warning=lambda *a, **k: None))

    assert parse_date(stub, "2024-06-01") == date(2024, 6, 1)
    assert parse_date(stub, "20240601") == date(2024, 6, 1)
    assert parse_date(stub, "") is None
    assert parse_date(stub, "---") is None


# ---------------------------------------------------------------------------------------------
# Wave 2: the row-value families (`operator` / `union-attr` / `str-bytes-safe`).
#
# PR #275 made `app/data_fetch/core/database.py` honest - `_DatabaseRow = RowType`, so a
# positional row is `Decimal | bytes | date | float | int | set[str] | str | timedelta | time |
# None` and every `.lower()`, `>`, `+=` or f-string on `row[0]` is now reported. Those reports
# were fixed per site against each column's own DDL, not with an ignore or a frozen baseline.
# The tests below are the red half of that bargain: each one pins the product output the
# narrowing claims, so a cast that names the wrong type, or an `isinstance` gate that quietly
# starts skipping rows, turns the corresponding test red.
# ---------------------------------------------------------------------------------------------


class _RecordingLogger:
    """Minimal stand-in for the script logger; keeps every emitted message for assertions."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _emit(self, level: str) -> object:
        def log(message: object, *args: object, **kwargs: object) -> None:
            self.records.append((level, str(message)))

        return log

    def __getattr__(self, level: str) -> object:
        return self._emit(level)

    def messages(self, level: str | None = None) -> list[str]:
        return [text for name, text in self.records if level is None or name == level]


class _StubCursor:
    """A positional cursor: `execute()` records SQL, `fetchall/fetchone` replay canned rows."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.statements: list[str] = []

    def execute(self, operation: str, params: object = ()) -> None:
        self.statements.append(operation)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None


def _stubbed_service(cls: type, **attrs: object) -> object:
    """An instance without `__init__`, so no stubbed script ever touches MySQL."""
    service = object.__new__(cls)
    for name, value in attrs.items():
        setattr(service, name, value)
    return service


def _dce_frame(product: str) -> pd.DataFrame:
    """One akshare-style 交割配对 row, in the source column names the script renames."""
    return pd.DataFrame(
        {
            "合约号": [f"{product.upper()}2609"],
            "配对日期": ["2026-06-18"],
            "买会员号": ["0101"],
            "卖会员号": ["0202"],
            "配对手数": [12],
            "交割结算价": [3456.75],
        }
    )


def _dce_service(
    rows: list[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_products: tuple[str, ...] = (),
) -> tuple[object, dict[str, list]]:
    """Wire `FuturesDeliveryMatchDce.run()` to a stub cursor + stub akshare provider."""
    from app.data_fetch.scripts.futures.weekly import dce_delivery_match

    # The loop sleeps 5s between products; the per-symbol pacing is not under test.
    monkeypatch.setattr(dce_delivery_match, "time", SimpleNamespace(sleep=lambda _s: None))
    FuturesDeliveryMatchDce = dce_delivery_match.FuturesDeliveryMatchDce

    seen: dict[str, list] = {"symbols": [], "saved": [], "conditions": []}

    def fake_fetch_ak_data(function_name: str, symbol: str, **kwargs: object) -> pd.DataFrame:
        seen["symbols"].append(symbol)
        if symbol in fail_products:
            raise RuntimeError(f"akshare unavailable for {symbol}")
        return _dce_frame(symbol)

    service = _stubbed_service(
        FuturesDeliveryMatchDce,
        table_name="FUTURES_DELIVERY_MATCH_DCE",
        create_table_sql="CREATE TABLE FUTURES_DELIVERY_MATCH_DCE",
        contract_units={"jd": "吨"},
        logger=_RecordingLogger(),
        table_exists=lambda name: True,
        create_table=lambda sql: None,
        connect_db=lambda: None,
        disconnect_db=lambda: None,
        require_cursor=lambda: _StubCursor(rows),
        fetch_ak_data=fake_fetch_ak_data,
        get_uuid=lambda: "r-id",
        get_current_datetime=lambda: "2026-06-19 09:00:00",
        get_latest_date=lambda table, column, conditions=None: (
            seen["conditions"].append(dict(conditions or {})) or "2026-06-01"
        ),
        save_data=lambda df, table_name, **kwargs: seen["saved"].append(df.copy()) or len(df),
    )
    return service, seen


def test_dce_symbols_reach_the_provider_as_lowercased_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DDL `FUTURES_TRADING_RULES.REFERENCE_NAME VARCHAR(100) NOT NULL` -> `cast(str, row[0])`.

    The lower-cased symbol is the provider argument, the `PRODUCT_CATEGORY` column and the
    incremental-read condition at once, so the whole chain is observed here. Dropping the
    narrowing, or turning it into an `isinstance` skip, loses rows or writes the wrong category.
    """
    service, seen = _dce_service([("JD",), ("LH",)], monkeypatch)
    result = service.run()

    assert seen["symbols"] == ["jd", "lh"]
    assert [frame["PRODUCT_CATEGORY"].tolist() for frame in seen["saved"]] == [["jd"], ["lh"]]
    # `contract_units` is keyed by the lower-cased string, so the unit lookup is the same claim.
    assert seen["saved"][0]["UNIT"].tolist() == ["吨"]
    assert seen["saved"][1]["UNIT"].tolist() == ["未知"]
    assert seen["conditions"] == [{"PRODUCT_CATEGORY": "jd"}, {"PRODUCT_CATEGORY": "lh"}]
    assert len(result) == 2


def test_dce_per_symbol_failure_still_summarises_with_string_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure path formats and `', '.join()`s the symbols - bytes there is a TypeError.

    This is what the `str-bytes-safe` reports on lines 80/82/92/100/194-199 were about: the f-
    strings and the summary join only work while `row[0]` really is the VARCHAR the DDL declares.
    """
    service, seen = _dce_service([("JD",), ("LH",)], monkeypatch, fail_products=("jd",))
    result = service.run()

    assert seen["symbols"] == ["jd", "lh"]
    assert [frame["PRODUCT_CATEGORY"].tolist() for frame in seen["saved"]] == [["lh"]]
    assert service.logger.messages("warning")[-1] == "以下品种的数据处理失败: jd"
    assert len(result) == 1


def test_dce_cast_is_a_claim_not_a_coercion(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cast()` erases at runtime, so a row that breaks the DDL contract still fails loudly.

    `REFERENCE_NAME` is `VARCHAR(100) NOT NULL`, so a NULL row cannot come from a conformant table;
    this case exists to keep the narrowing honest. The `.lower()` sits outside the per-symbol try,
    so such a row aborts `run()` - before this change and after it, unchanged. Coercing at the read
    (`str(row[0])`) would instead fetch and store a product literally named "none", and an
    `isinstance` skip would drop the symbol without a trace; both are red here.
    """
    service, seen = _dce_service([("JD",), (None,)], monkeypatch)
    with pytest.raises(AttributeError):
        service.run()

    assert seen["symbols"] == ["jd"], "the readable row still runs, the broken one is never fetched"
    assert [frame["PRODUCT_CATEGORY"].tolist() for frame in seen["saved"]] == [["jd"]]


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([(1,)], True),
        ([(0,)], False),
        ([], False),
        # COUNT(*) is BIGINT, but the claim being pinned is "the value is compared, not gated":
        # an `isinstance(count, int)` narrowing would make this row False and break the calendar.
        ([(Decimal("2"),)], True),
    ],
)
def test_is_trading_day_compares_the_count_it_was_handed(rows: list[tuple], expected: bool) -> None:
    from app.data_fetch.scripts.common.monthly.trading_days import TradingDaysUpdater

    service = _stubbed_service(
        TradingDaysUpdater,
        table_name="TRADING_DAYS",
        logger=_RecordingLogger(),
        connect_db=lambda: None,
        disconnect_db=lambda: None,
        require_cursor=lambda: _StubCursor(rows),
    )

    assert service.is_trading_day(date(2026, 6, 18)) is expected


def _sw_service(latest_date: str | None) -> tuple[object, list[tuple[str, str, str]]]:
    """`SWIndexAnalysisDaily` with a stubbed stored-date lookup; jobs come out as `calls`."""
    from app.data_fetch.scripts.indexs.weekly.sw_index_analysis_daily import SWIndexAnalysisDaily

    calls: list[tuple[str, str, str]] = []

    def fake_fetch_analysis_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        calls.append((symbol, start_date, end_date))
        return pd.DataFrame()

    service = _stubbed_service(
        SWIndexAnalysisDaily,
        table_name="SW_INDEX_ANALYSIS_DAILY",
        create_table_sql="CREATE TABLE SW_INDEX_ANALYSIS_DAILY",
        valid_symbols=["市场表征"],
        logger=_RecordingLogger(),
        table_exists=lambda name: True,
        get_current_date=lambda: "2026-06-20",
        get_latest_date=lambda table, column, conditions=None: latest_date,
        fetch_analysis_data=fake_fetch_analysis_data,
    )
    return service, calls


@pytest.mark.parametrize(
    ("kwargs", "latest", "expected_start"),
    [
        # incremental: the stored date, normalised.
        ({}, "2026-06-19", "20260619"),
        # update_all: the full-history floor constant, never the seeded default.
        ({"update_all": True}, "2026-06-19", "20050104"),
        # empty table: `_get_default_start_date()`'s own floor, the same constant.
        ({}, None, "20050104"),
        # lookback floor wins when it is later than the stored date: str/str `max()`.
        ({"lookback_days": 5}, "2026-06-01", "20260615"),
    ],
)
def test_sw_analysis_start_date_resolves_without_reaching_a_none_comparison(
    kwargs: dict, latest: str | None, expected_start: str
) -> None:
    """Every branch must produce a *job*, i.e. survive `resolved_start_date > end_date`.

    A `None` still living in `default_start_date` would raise inside `run()` and be swallowed by
    its blanket handler, which returns False with zero jobs - so this asserts both halves.
    """
    service, calls = _sw_service(latest)

    assert service.run(symbol="市场表征", max_workers=1, **kwargs) is True
    assert calls == [("市场表征", expected_start, "20260620")]


def test_catalog_batch_stats_keep_counters_and_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_CatalogStats` types the counters the loop writes; the payload shape is unchanged.

    The four `operator` reports here were `object + int` because the dict literal mixed ints with
    `catalog_source`; naming the shape must not move a counter, rename a key, or disturb the
    pre-existing 20-entry failure cap. 22 endpoints with 2 successes keeps every counter additive.
    """
    from app.data_fetch.scripts.common.hourly import akshare_catalog_batch

    rows_by_endpoint = {"endpoint_0": 7, "endpoint_1": 5}

    def fake_run_endpoint(**kwargs: object) -> dict:
        name = str(kwargs["endpoint_name"])
        if name in rows_by_endpoint:
            return {"success": True, "rows": rows_by_endpoint[name]}
        raise RuntimeError(f"{name} is not callable")

    endpoints = {f"endpoint_{index}": {} for index in range(25)}
    monkeypatch.setattr(
        akshare_catalog_batch, "_load_endpoint_catalog", lambda: (endpoints, "file")
    )
    monkeypatch.setattr(akshare_catalog_batch, "run_endpoint", fake_run_endpoint)
    monkeypatch.setenv("AKSHARE_CATALOG_CALL_TIMEOUT", "9")

    result = akshare_catalog_batch.run(batch_size=25, batch_index=0)

    assert result["stats"] == {
        "selected": 25,
        "ok": 2,
        "failed": 23,
        "rows": 12,
        "catalog_source": "file",
        "call_timeout": 9,
    }
    assert result["success"] is False
    assert len(result["failures"]) == 20, "the failure cap is part of the payload contract"
    assert {f["endpoint"] for f in result["failures"]} <= set(endpoints)


def test_minute_variety_binds_one_match_and_keeps_the_empty_branch() -> None:
    """`re.match(...).group() if re.match(...)` became one bound call; DDL keeps `""` legal.

    `VARIETY` is `VARCHAR(10)` and the else-branch stores "", so both halves of the ternary are
    product output. Calling the matcher twice left the guard unable to narrow the dereference.
    """
    from app.data_fetch.scripts.futures.daily.minute_market import FuturesMinuteMarket

    saved: dict[str, pd.DataFrame] = {}

    service = _stubbed_service(
        FuturesMinuteMarket,
        table_name="FUTURES_MINUTE_MARKET",
        logger=_RecordingLogger(),
        connect_db=lambda: None,
        disconnect_db=lambda: None,
        require_cursor=lambda: _StubCursor([]),
        get_uuid=lambda: "r-id",
        save_data=lambda df, table_name, **kwargs: saved.__setitem__("df", df.copy()),
    )
    frame = pd.DataFrame(
        {
            "datetime": ["2026-06-18 09:31:00", "2026-06-18 09:32:00"],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [10, 20],
            "hold": [100, 100],
        }
    )
    service._save_symbol_minute_data("rb2401", "1min", frame, "FUTURES_MINUTE_MARKET")

    assert saved["df"]["VARIETY"].tolist() == ["RB", "RB"]
    assert saved["df"]["SYMBOL"].tolist() == ["rb2401", "rb2401"]

    saved.clear()
    service._save_symbol_minute_data("2401", "1min", frame, "FUTURES_MINUTE_MARKET")
    assert saved["df"]["VARIETY"].tolist() == ["", ""]


def test_minute_keeps_the_full_fetch_path_when_the_stored_row_is_bytes() -> None:
    """Why the narrowing here is the matcher and not `row[0]`: TEXT/BINARY reads can be bytes.

    `_format_latest_datetime` runs the row through `pd.to_datetime(..., errors="coerce")`, so an
    unreadable bytes row becomes "no stored history" and every bar is written. A row coerced with
    `str(b"...")` and then *used* as the incremental filter would drop the whole frame instead -
    that is the difference this test pins, next to the readable-str row that does filter.
    """
    from app.data_fetch.scripts.futures.daily.minute_market import FuturesMinuteMarket

    frame = pd.DataFrame(
        {
            "datetime": ["2026-06-18 09:31:00", "2026-06-18 09:32:00"],
            "open": [1.0, 2.0],
            "high": [1.0, 2.0],
            "low": [1.0, 2.0],
            "close": [1.0, 2.0],
            "volume": [10, 20],
            "hold": [100, 100],
        }
    )

    def service_with(rows: list[tuple[object, ...]]) -> tuple[object, dict]:
        saved: dict[str, pd.DataFrame] = {}
        service = _stubbed_service(
            FuturesMinuteMarket,
            table_name="FUTURES_MINUTE_MARKET",
            logger=_RecordingLogger(),
            connect_db=lambda: None,
            disconnect_db=lambda: None,
            require_cursor=lambda: _StubCursor(rows),
            get_uuid=lambda: "r-id",
            save_data=lambda df, table_name, **kwargs: saved.__setitem__("df", df.copy()),
        )
        return service, saved

    service, saved = service_with([(b"2026-06-18 09:30:00",)])
    service._save_symbol_minute_data("IF0", "1min", frame, "FUTURES_MINUTE_MARKET")
    assert len(saved["df"]) == 2, "a bytes row must not become an incremental filter value"
    assert service.logger.messages("info")[0].startswith("No existing data for IF0")

    service, saved = service_with([("2026-06-18 09:32:00",)])
    service._save_symbol_minute_data("IF0", "1min", frame, "FUTURES_MINUTE_MARKET")
    assert saved["df"]["TRADE_DATETIME"].tolist() == ["2026-06-18 09:32:00"]


def test_no_script_narrows_a_recalled_call() -> None:
    """`f(...) ... if f(...)` - the guard is a second call, so it cannot narrow the first.

    `minute_market.py` was the only offender in the plane (one `union-attr`), and binding the
    matcher is what cleared it; this census is the red half of that fix.
    """
    offenders = [
        f"{p.relative_to(SCRIPT_ROOT.parent.parent)}:{line}"
        for p in _scripts()
        for line in _recalled_call_guards(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"guards that re-call instead of narrowing: {offenders[:10]}"
