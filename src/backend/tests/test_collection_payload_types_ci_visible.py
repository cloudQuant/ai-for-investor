"""Pin the request payload shapes that five CI-visible mypy errors were about.

On the CI environment (Python 3.11 + `config/requirements-dev.lock`) the collection plane carried
five errors that a laptop venv could not see, because `requests` is untyped `Any` there:
four `Argument "json" to "post" has incompatible type ...; expected "JsonType"` and one
`str | AttributeValueList` assignment. The fixes are type annotations plus one isinstance narrowing,
so these tests assert the **runtime payload is unchanged** -- an annotation that quietly altered what
gets posted would pass mypy and fail here.
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("bs4", reason="optional bs4 package is required")
pytest.importorskip("requests", reason="requests is required by these scripts")

# the three scripts differ only in marketType: the HK ranking asks for market 000003
MODULES = (
    ("app.data_fetch.scripts.stocks.daily.stock_hot_up_em", ""),
    ("app.data_fetch.scripts.stocks.daily.stock_hot_rank_em", ""),
    ("app.data_fetch.scripts.stocks.daily.stock_hk_hot_rank_em", "000003"),
)


class _Captured(Exception):
    pass


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"data": []}


@pytest.mark.parametrize("module_name,market_type", MODULES)
def test_stock_hot_payload_sends_exactly_these_fields(
    module_name, market_type, monkeypatch
) -> None:
    module = importlib.import_module(module_name)
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse()

    monkeypatch.setattr(module.requests, "post", fake_post)
    class_name = [n for n in dir(module) if n.startswith("Stock")][0]
    getattr(module, class_name).fetch_rank(page_size=50)

    payload = captured["json"]
    assert payload == {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": market_type,
        "pageNo": 1,
        "pageSize": 50,
    }, "the annotation must not have changed what is posted"
    assert all(isinstance(v, (str, int)) for v in payload.values())


def test_macro_payload_keeps_its_list_shapes(monkeypatch) -> None:
    module = importlib.import_module(
        "app.data_fetch.scripts.common.daily.macro_china_urban_unemployment"
    )
    base = module.MacroChinaUrbanUnemployment.__mro__[1]
    monkeypatch.setattr(base, "__init__", lambda self, *a, **k: None)

    client = module.MacroChinaUrbanUnemployment()
    payload = client.payload

    assert payload["cid"] == "ee3b7046b390415b9b7745e3d16f6052"
    assert isinstance(payload["indicatorIds"], list)
    assert all(isinstance(item, str) for item in payload["indicatorIds"])
    assert payload["das"] == [{"text": "全国", "value": "000000000000"}]
    assert payload["dts"] == ["199001MM-203601MM"]
    assert payload["showType"] == "1"


def test_spot_futures_parser_skips_missing_and_non_str_hrefs(monkeypatch) -> None:
    module = importlib.import_module("app.data_fetch.scripts.futures.hourly.futures_spot_sys")
    html = """
    <div class="q8">
      <ul>
        <li><a href="/sf/1.html">螺纹钢</a></li>
        <li><a>没有链接</a></li>
        <li><a href="">空链接</a></li>
      </ul>
    </div>
    """

    class _Html:
        text = html

    monkeypatch.setattr(module, "_get_100ppi", lambda session, url: _Html())
    result = module._get_sys_spot_futures_dict(None)

    assert result == {"螺纹钢": "/sf/1.html"}, "missing/empty hrefs must be skipped, not stored"
