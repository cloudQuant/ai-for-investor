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
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest

pytest.importorskip("akshare", reason="optional akshare provider package is required")

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


def test_the_rebinding_census_finds_the_shape_it_is_meant_to_prevent() -> None:
    assert _set_list_rebindings(SET_TO_LIST_SAMPLE) == [("run", "codes_to_fetch")]


def test_the_double_get_census_finds_the_shape_it_is_meant_to_prevent() -> None:
    assert _double_get_guards(DOUBLE_GET_SAMPLE)


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
