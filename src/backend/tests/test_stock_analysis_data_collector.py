"""Regression coverage for the stock-analysis data collection boundary."""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from app.services.stock_analysis.analysis_engine import StockAnalysisEngine
from app.services.stock_analysis.data_collector import StockAnalysisDataCollector
from app.services.stock_analysis.pipeline import StockAnalysisPipeline


class _RefreshAwareMarketService:
    """Expose whether the collector stays on the persisted market-data path."""

    async def lookup(self, **kwargs):
        assert kwargs["refresh_online"] is False
        history_date = "2026-07-30"
        price = 11.61
        return {
            "symbol": "000001",
            "name": "平安银行",
            "provider": "akshare_data",
            "snapshot": {
                "symbol": "000001",
                "name": "平安银行",
                "price": price,
                "update_time": history_date,
            },
            "history": {
                "rows": [
                    {
                        "date": history_date,
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": 100,
                    }
                ]
            },
            "indicators": {},
        }


class _EmptyNewsLibrary:
    async def list_articles(self, _user_id: str, *, ticker: str):
        assert ticker in {"000001.SZ", "000001"}
        return {"items": [], "total": 0}


class _NoNewsLibrary:
    """Return an empty local library without constraining the test ticker."""

    async def list_articles(self, _user_id: str, *, ticker: str):
        return {"items": [], "total": 0}


class _CompanyProfileMarketService:
    """Supply the sparse quote payload that previously caused the warning."""

    async def lookup(self, **kwargs):
        assert kwargs["refresh_online"] is False
        return {
            "symbol": "601398.SH",
            "name": "601398.SH",
            "provider": "akshare_data",
            "snapshot": {
                "symbol": "601398.SH",
                "name": "601398.SH",
                "price": 8.15,
                "update_time": "2026-07-30",
            },
            "history": {
                "rows": [
                    {
                        "date": "2026-07-30",
                        "open": 8.0,
                        "high": 8.2,
                        "low": 7.9,
                        "close": 8.15,
                        "volume": 100,
                    }
                ]
            },
            "indicators": {},
        }


@pytest.mark.asyncio
async def test_collect_uses_current_cn_market_financial_and_news_data(
    monkeypatch: pytest.MonkeyPatch,
):
    """A stock analysis reads its persisted market-data result through the local path."""
    financial_abstract = pd.DataFrame(
        [
            {"选项": "常用指标", "指标": "营业总收入", "20260331": 35.0, "20251231": 130.0},
            {"选项": "常用指标", "指标": "归母净利润", "20260331": 14.0, "20251231": 42.0},
            {"选项": "常用指标", "指标": "基本每股收益", "20260331": 0.67, "20251231": 2.07},
            {"选项": "常用指标", "指标": "净资产收益率(ROE)", "20260331": 2.83, "20251231": 9.15},
        ]
    )
    financial_indicators = pd.DataFrame(
        [
            {
                "日期": "2026-03-31",
                "主营业务收入增长率(%)": 4.65,
                "净利润增长率(%)": 3.03,
            },
            {
                "日期": "2025-12-31",
                "主营业务收入增长率(%)": -10.4,
                "净利润增长率(%)": -4.21,
            },
        ]
    )
    stock_news = pd.DataFrame(
        [
            {
                "新闻标题": "平安银行发布最新经营数据",
                "新闻内容": "测试新闻正文",
                "发布时间": "2026-07-30 10:00:00",
                "文章来源": "证券时报网",
                "新闻链接": "https://example.test/news/1",
            }
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_financial_abstract=lambda *, symbol: financial_abstract,
            stock_financial_analysis_indicator=lambda *, symbol, start_year: financial_indicators,
            stock_news_em=lambda *, symbol: stock_news,
        ),
    )
    monkeypatch.setattr(
        "app.services.stock_analysis.data_collector.get_news_intelligence_service",
        lambda _db: _EmptyNewsLibrary(),
    )

    collector = StockAnalysisDataCollector(db=SimpleNamespace())
    collector.market_service = _RefreshAwareMarketService()

    snapshot = await collector.collect(
        user_id="collector-test-user",
        symbol="000001.SZ",
        market_type="A股",
        analysis_date=date(2026, 7, 30),
    )

    assert snapshot["history"]["rows"][-1]["date"] == "2026-07-30"
    assert snapshot["financials"]["annual"] == [
        {
            "report_date": "2025-12-31",
            "revenue": 130.0,
            "net_income": 42.0,
            "eps": 2.07,
            "roe": 9.15,
            "revenue_growth": -10.4,
            "profit_growth": -4.21,
        }
    ]
    assert snapshot["financials"]["quarterly"] == [
        {
            "report_date": "2026-03-31",
            "revenue": 35.0,
            "net_income": 14.0,
            "eps": 0.67,
            "roe": 2.83,
            "revenue_growth": 4.65,
            "profit_growth": 3.03,
        }
    ]
    assert snapshot["news"]["total"] == 1
    assert snapshot["news"]["items"][0]["headline"] == "平安银行发布最新经营数据"
    assert snapshot["news"]["items"][0]["sentiment"] == "UNKNOWN"
    assert snapshot["data_quality"]["degraded_reasons"] == []


def test_cn_news_normalization_marks_unsupported_headlines_unknown_not_neutral() -> None:
    news = pd.DataFrame(
        [
            {"新闻标题": "公司公告", "新闻内容": "例行信息披露"},
            {"新闻标题": "业绩增长并获批新业务", "新闻内容": ""},
            {"新闻标题": "收到监管处罚", "新闻内容": ""},
        ]
    )

    items = StockAnalysisDataCollector._normalize_cn_news(news, "000001.SZ")

    assert [item["sentiment"] for item in items] == ["UNKNOWN", "BULLISH", "BEARISH"]


@pytest.mark.asyncio
async def test_collect_enriches_cn_company_profile_and_industry_peers(
    monkeypatch: pytest.MonkeyPatch,
):
    """A-share reports must carry real company context rather than an empty info shell."""
    company_profile = pd.DataFrame(
        [
            {"item": "org_short_name_cn", "value": "中国工商银行"},
            {
                "item": "main_operation_business",
                "value": "从事公司和个人金融业务、资金业务、投资银行业务，并提供资产管理等金融服务。",
            },
            {"item": "affiliate_industry", "value": {"ind_name": "银行"}},
        ]
    )
    industry_members = pd.DataFrame(
        [
            {"代码": "601398", "名称": "工商银行"},
            {"代码": "601939", "名称": "建设银行"},
            {"代码": "601288", "名称": "农业银行"},
            {"代码": "601988", "名称": "中国银行"},
        ]
    )
    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(
            stock_financial_abstract=lambda *, symbol: pd.DataFrame(),
            stock_financial_analysis_indicator=lambda *, symbol, start_year: pd.DataFrame(),
            stock_news_em=lambda *, symbol: pd.DataFrame(),
            stock_individual_basic_info_xq=lambda *, symbol: company_profile,
            stock_board_industry_cons_em=lambda *, symbol: industry_members,
        ),
    )
    monkeypatch.setattr(
        "app.services.stock_analysis.data_collector.get_news_intelligence_service",
        lambda _db: _NoNewsLibrary(),
    )
    collector = StockAnalysisDataCollector(db=SimpleNamespace())
    collector.market_service = _CompanyProfileMarketService()

    snapshot = await collector.collect(
        user_id="company-profile-test-user",
        symbol="601398.SH",
        market_type="A股",
        analysis_date=date(2026, 7, 30),
    )

    assert snapshot["info"]["name"] == "中国工商银行"
    assert snapshot["info"]["sector"] == "金融业"
    assert snapshot["info"]["industry"] == "银行"
    assert snapshot["info"]["description"] == (
        "从事公司和个人金融业务、资金业务、投资银行业务，并提供资产管理等金融服务。"
    )
    assert snapshot["peers"] == {
        "items": [
            {"symbol": "601939.SH", "name": "建设银行", "industry": "银行"},
            {"symbol": "601288.SH", "name": "农业银行", "industry": "银行"},
            {"symbol": "601988.SH", "name": "中国银行", "industry": "银行"},
        ],
        "total": 3,
        "provider": "akshare",
    }


def test_ai_source_context_includes_company_profile_and_industry_peers():
    """AI stages need the enriched context, not just the rule-based report."""
    engine = StockAnalysisEngine(
        SimpleNamespace(),
        ai_router=SimpleNamespace(),
        model_preference_service=SimpleNamespace(),
        settings=SimpleNamespace(),
    )

    source_context = json.loads(
        engine._source_context(
            {
                "info": {
                    "name": "中国工商银行",
                    "industry": "银行",
                    "description": "从事公司和个人金融业务。",
                },
                "peers": {
                    "items": [{"symbol": "601939.SH", "name": "建设银行", "industry": "银行"}],
                    "total": 1,
                    "provider": "akshare",
                },
            }
        )
    )

    assert source_context["info"]["description"] == "从事公司和个人金融业务。"
    assert source_context["peers"]["items"][0]["symbol"] == "601939.SH"


@pytest.mark.asyncio
async def test_pipeline_uses_latest_report_period_not_only_annual_data():
    """The fundamentals narrative must label a report period, not an announcement date."""
    output = await StockAnalysisPipeline().run(
        symbol="000001.SZ",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {"symbol": "000001.SZ", "name": "平安银行", "price": 11.61},
            "info": {"symbol": "000001.SZ", "name": "平安银行"},
            "history": {
                "rows": [
                    {
                        "date": "2026-07-30",
                        "open": 11.28,
                        "high": 11.62,
                        "low": 11.18,
                        "close": 11.61,
                        "volume": 100,
                    }
                ]
            },
            "technicals": {"factors": {}},
            "financials": {
                "annual": [
                    {
                        "report_date": "2025-12-31",
                        "revenue": 130.0,
                        "net_income": 42.0,
                        "eps": 2.07,
                        "roe": 9.15,
                    }
                ],
                "quarterly": [
                    {
                        "report_date": "2026-03-31",
                        "revenue": 35.0,
                        "net_income": 14.0,
                        "eps": 0.67,
                        "roe": 2.83,
                    }
                ],
            },
            "news": {"items": [], "total": 0},
        },
    )

    assert "报告期截止日：2026-03-31" in output["fundamentals_report"]
    assert "本报告期收入：35.0" in output["fundamentals_report"]
    assert "ROE 原始值：2.83（单位与口径待确认）" in output["fundamentals_report"]
    assert "当前价格与本报告期 EPS 的比值为 17.33" in output["fundamentals_report"]
    assert "静态市盈率约" not in output["fundamentals_report"]
    assert "最新披露日期" not in output["fundamentals_report"]
    assert "稳定股东回报" not in output["fundamentals_report"]
    assert "ROE 维持在两位数" not in output["fundamentals_report"]
    assert "收入同比变化约 数据不足" in output["fundamentals_report"]
    assert "净利润同比变化约 数据不足" in output["fundamentals_report"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "report_date",
        "net_income",
        "roe",
        "expected_date",
        "expected_profit",
        "expected_roe",
        "expected_eps_ratio",
    ),
    [
        (
            "2026-03-31",
            14.0,
            0.83,
            "报告期截止日：2026-03-31",
            "本报告期净利润为 14.0（本条记录为正）。",
            "本报告期 ROE 原始值为 0.83（单位与口径待确认）。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            -1.0,
            -3.2,
            "报告期截止日：2026-03-31",
            "本报告期净利润为 -1.0（本条记录为负）。",
            "本报告期 ROE 原始值为 -3.2（单位与口径待确认）。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            None,
            0.83,
            "报告期截止日：2026-03-31",
            "本报告期净利润数据不足，无法判断盈亏。",
            "本报告期 ROE 原始值为 0.83（单位与口径待确认）。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            14.0,
            None,
            "报告期截止日：2026-03-31",
            "本报告期净利润为 14.0（本条记录为正）。",
            "本报告期 ROE 数据不足，单位与口径待确认。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            -1.0,
            12.0,
            "报告期截止日：2026-03-31",
            "本报告期净利润为 -1.0（本条记录为负）。",
            "本报告期 ROE 原始值为 12.0（单位与口径待确认）。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            None,
            None,
            0.83,
            "报告期截止日：数据不足",
            "当前财务记录净利润数据不足，无法判断盈亏。",
            "当前财务记录 ROE 原始值为 0.83（单位与口径待确认）。",
            "当前价格与当前财务记录 EPS 的比值为 17.33",
        ),
        (
            None,
            14.0,
            None,
            "报告期截止日：数据不足",
            "当前财务记录净利润为 14.0（本条记录为正）。",
            "当前财务记录 ROE 数据不足，单位与口径待确认。",
            "当前价格与当前财务记录 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            -1.0,
            None,
            "报告期截止日：2026-03-31",
            "本报告期净利润为 -1.0（本条记录为负）。",
            "本报告期 ROE 数据不足，单位与口径待确认。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            None,
            None,
            "报告期截止日：2026-03-31",
            "本报告期净利润数据不足，无法判断盈亏。",
            "本报告期 ROE 数据不足，单位与口径待确认。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
        (
            None,
            None,
            None,
            "报告期截止日：数据不足",
            "当前财务记录净利润数据不足，无法判断盈亏。",
            "当前财务记录 ROE 数据不足，单位与口径待确认。",
            "当前价格与当前财务记录 EPS 的比值为 17.33",
        ),
        (
            "2026-03-31",
            float("nan"),
            float("nan"),
            "报告期截止日：2026-03-31",
            "本报告期净利润数据不足，无法判断盈亏。",
            "本报告期 ROE 数据不足，单位与口径待确认。",
            "当前价格与本报告期 EPS 的比值为 17.33",
        ),
    ],
)
async def test_fundamentals_report_uses_raw_values_without_unverified_units(
    report_date: str | None,
    net_income: float | None,
    roe: float | None,
    expected_date: str,
    expected_profit: str,
    expected_roe: str,
    expected_eps_ratio: str,
) -> None:
    report_period = {
        "revenue": 35.0,
        "eps": 0.67,
    }
    if report_date is not None:
        report_period["report_date"] = report_date
    if net_income is not None:
        report_period["net_income"] = net_income
    if roe is not None:
        report_period["roe"] = roe

    output = await StockAnalysisPipeline().run(
        symbol="000001.SZ",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {"symbol": "000001.SZ", "name": "平安银行", "price": 11.61},
            "info": {"symbol": "000001.SZ", "name": "平安银行"},
            "history": {"rows": []},
            "technicals": {"factors": {}},
            "financials": {"annual": [], "quarterly": [report_period]},
            "news": {"items": [], "total": 0},
        },
    )

    fundamentals = output["fundamentals_report"]
    assert expected_date in fundamentals
    assert expected_profit in fundamentals
    assert expected_roe in fundamentals
    assert expected_eps_ratio in fundamentals
    assert "静态市盈率约" not in fundamentals
    if report_date is None:
        assert "本报告期" not in fundamentals
        assert "单条财务记录不足以判断盈利稳定性" in fundamentals
    else:
        assert "单个报告期指标不足以判断盈利稳定性" in fundamentals
    assert "当前财务记录不含股息或派息指标，无法评价股东回报。" in fundamentals

    bull = output["bull_researcher"]
    assert "盈利能力、行业地位和估值防守仍需数据验证" in bull
    if net_income is None or not math.isfinite(net_income):
        assert "净利润为 数据不足" in bull
    else:
        assert f"净利润为 {net_income}" in bull
    if roe is None or not math.isfinite(roe):
        assert "ROE 为 数据不足" in bull
    else:
        assert f"ROE 为 {roe}" in bull

    downstream = "\n".join(
        output[key]
        for key in (
            "bull_researcher",
            "bear_researcher",
            "research_team_decision",
            "risky_analyst",
            "safe_analyst",
            "neutral_analyst",
            "risk_management_decision",
        )
    )
    assert "最新披露" not in downstream
    assert "稳定股东回报" not in downstream
    assert "ROE 维持在两位数" not in downstream
    assert "基本面稳定并不等于" not in downstream
    assert "多方强调基本面稳定" not in downstream
    assert "稳定盈利资产" not in downstream
    if report_date is None:
        assert "本报告期" not in downstream

    manager_decision = output["research_team_decision"]
    if (net_income is None or not math.isfinite(net_income)) and (
        roe is None or not math.isfinite(roe)
    ):
        assert "净利润和 ROE 均缺少有效数值，无法据此判断盈利能力。" in manager_decision
        assert "净利润或 ROE 指标" not in output["neutral_analyst"]
        assert "净利润和 ROE 均缺少有效数值" in output["neutral_analyst"]
        assert "净利润和 ROE 均缺少有效数值" in output["risk_management_decision"]
        assert "提供净利润或 ROE 字段参考" not in output["risk_management_decision"]
    else:
        assert "净利润和 ROE 均缺少有效数值" not in manager_decision


def test_pipeline_preserves_source_financial_yoy_values() -> None:
    """Use source-provided YoY fields without recalculating from adjacent reports."""
    pipeline = StockAnalysisPipeline()
    context = pipeline._analysis_context(
        symbol="000001.SZ",
        market_type="A股",
        snapshot={
            "analysis_date": "2026-07-30",
            "financials": {
                "annual": [
                    {"report_date": "2025-12-31", "revenue": 130.0, "net_income": 42.0}
                ],
                "quarterly": [
                    {
                        "report_date": "2026-03-31",
                        "revenue": 35.0,
                        "net_income": 14.0,
                        "revenue_growth": 4.65,
                        "profit_growth": 3.03,
                    }
                ],
            },
        },
        profile={},
    )

    assert context["revenue_growth"] == 4.65
    assert context["profit_growth"] == 3.03
    assert pipeline._format_pct(context["revenue_growth"]) == "4.65%"
    assert pipeline._format_pct(context["profit_growth"]) == "3.03%"


@pytest.mark.asyncio
async def test_pipeline_marks_missing_market_and_financial_data_unavailable_without_defaults() -> (
    None
):
    output = await StockAnalysisPipeline().run(
        symbol="601398.SH",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {},
            "info": {"symbol": "601398.SH", "name": "中国工商银行"},
            "history": {"rows": []},
            "technicals": {"factors": {}},
            "financials": {"annual": [], "quarterly": []},
            "news": {"items": [], "total": 0},
        },
    )

    assert output["decision"]["action"] == "观望"
    assert "技术维度不可用" in output["market_report"]
    assert "基本面维度不可用" in output["fundamentals_report"]
    assert "¥100.00" not in output["market_report"]
    assert "财务数据不可用" in output["bull_researcher"]


@pytest.mark.asyncio
async def test_trader_and_bear_reports_separate_quote_from_missing_financial_data() -> None:
    output = await StockAnalysisPipeline().run(
        symbol="601398.SH",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {"symbol": "601398.SH", "name": "中国工商银行", "price": 7.12},
            "info": {"symbol": "601398.SH", "name": "中国工商银行"},
            "history": {"rows": []},
            "technicals": {"factors": {}},
            "financials": {"annual": [], "quarterly": []},
            "news": {"items": [], "total": 0},
        },
    )

    trader_report = output["trader_investment_plan"]
    assert "有当前价格报价，但无历史收盘价样本，技术证据有限。" in trader_report
    assert "无有效财务记录，基本面证据不足。" in trader_report
    assert "本处未独立验证数据质量。" in trader_report
    assert "质量检查" not in trader_report
    assert "目前基本面比技术面更强" not in trader_report
    assert "缺少历史收盘价样本，无法确认高点折让或回归空间。" in output[
        "bull_researcher"
    ]
    assert "历史收盘价样本不足，无法确认短期均线压力。" in output["bull_researcher"]
    assert "财务记录缺失，无法基于财务指标验证盈利能力或基本面稳定性。" in output[
        "bear_researcher"
    ]
    assert "历史收盘价样本不足，无法判断短线趋势压力或是否反转。" in output[
        "bear_researcher"
    ]
    assert "本次未收集到新闻样本，无法判断催化方向。" in output["bear_researcher"]
    assert "当前最大的风险是短线趋势和催化不足" not in output["bear_researcher"]
    assert "暂不据此确认压力位或防守位" in output["bear_researcher"]


@pytest.mark.asyncio
async def test_trader_and_bear_reports_note_missing_metrics_in_existing_financial_record() -> None:
    output = await StockAnalysisPipeline().run(
        symbol="601398.SH",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {"symbol": "601398.SH", "name": "中国工商银行", "price": 7.12},
            "info": {"symbol": "601398.SH", "name": "中国工商银行"},
            "history": {"rows": []},
            "technicals": {"factors": {}},
            "financials": {
                "annual": [],
                "quarterly": [{"report_date": "2026-03-31", "revenue": 80.0, "eps": 0.3}],
            },
            "news": {"items": [], "total": 0},
        },
    )

    trader_report = output["trader_investment_plan"]
    assert "有当前价格报价，但无历史收盘价样本，技术证据有限。" in trader_report
    assert "有财务记录，但净利润和 ROE 均缺少有效数值，基本面证据不足。" in trader_report
    assert "质量检查" not in trader_report
    assert "缺少历史收盘价样本，无法确认高点折让或回归空间。" in output[
        "bull_researcher"
    ]
    assert (
        "当前报告期财务记录存在，但净利润和 ROE 均缺少有效数值，"
        "无法据此验证盈利能力或基本面稳定性。"
    ) in output["bear_researcher"]


@pytest.mark.asyncio
async def test_bear_report_respects_positive_trend_and_available_news_samples() -> None:
    output = await StockAnalysisPipeline().run(
        symbol="601398.SH",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {"symbol": "601398.SH", "name": "中国工商银行", "price": 11.2},
            "info": {"symbol": "601398.SH", "name": "中国工商银行"},
            "history": {
                "rows": [
                    {"date": "2026-07-28", "close": 10.0},
                    {"date": "2026-07-29", "close": 10.5},
                    {"date": "2026-07-30", "close": 11.0},
                ]
            },
            "technicals": {"factors": {}},
            "financials": {"annual": [], "quarterly": []},
            "news": {"items": [{"headline": "业绩公告"}], "total": 1},
        },
    )

    bear_report = output["bear_researcher"]
    assert "当前技术信号偏强，未显示明确的短线趋势压力。" in bear_report
    assert "本次收集到 1 条新闻样本，需结合内容评估催化方向。" in bear_report
    assert "当前最大的风险是短线趋势和催化不足" not in bear_report
    assert "无近期新闻会降低短线交易热度" not in bear_report
    assert "当前技术信号偏强，暂不支持短期均线承压的判断。" in output[
        "bull_researcher"
    ]


@pytest.mark.asyncio
async def test_bull_price_comparison_labels_history_fallback_as_reference_price() -> None:
    output = await StockAnalysisPipeline().run(
        symbol="601398.SH",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {},
            "info": {"symbol": "601398.SH", "name": "中国工商银行"},
            "history": {
                "rows": [
                    {"date": "2026-07-28", "close": 10.0},
                    {"date": "2026-07-29", "close": 12.0},
                    {"date": "2026-07-30", "close": 11.0},
                ]
            },
            "technicals": {"factors": {}},
            "financials": {"annual": [], "quarterly": []},
            "news": {"items": [], "total": 0},
        },
    )

    bull_report = output["bull_researcher"]
    assert "参考价格 ¥11.00 较历史收盘样本高点 ¥12.00 低约 8.33%" in bull_report
    assert "当前价 ¥11.00" not in bull_report


@pytest.mark.asyncio
async def test_fundamentals_report_treats_nonfinite_revenue_and_yoy_as_unavailable() -> None:
    output = await StockAnalysisPipeline().run(
        symbol="601398.SH",
        market_type="A股",
        research_depth="标准",
        selected_modules=["market", "fundamentals", "news", "risk"],
        snapshot={
            "analysis_date": "2026-07-30",
            "quote": {"symbol": "601398.SH", "name": "中国工商银行", "price": 7.12},
            "info": {"symbol": "601398.SH", "name": "中国工商银行"},
            "history": {"rows": []},
            "technicals": {"factors": {}},
            "financials": {
                "annual": [],
                "quarterly": [
                    {
                        "report_date": "2026-03-31",
                        "revenue": float("nan"),
                        "revenue_growth": float("inf"),
                        "profit_growth": float("nan"),
                    }
                ],
            },
            "news": {"items": [], "total": 0},
        },
    )

    report = output["fundamentals_report"]
    assert "收入：数据不足" in report
    assert "收入同比变化约 数据不足" in report
    assert "净利润同比变化约 数据不足" in report
    assert "nan" not in report.lower()
    assert "inf" not in report.lower()
