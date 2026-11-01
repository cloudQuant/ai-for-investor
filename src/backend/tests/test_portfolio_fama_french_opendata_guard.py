from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import app.services.portfolio_ledger_analytics as portfolio_ledger_analytics
from app.schemas.portfolio_ledger import PortfolioLedgerFamaFrenchRequest
from app.services.portfolio_ledger_analytics import PortfolioLedgerAnalyticsService


class _LedgerService:
    def __init__(self, context: dict[str, object] | None) -> None:
        self.analytics_context = AsyncMock(return_value=context)


def _context(*, benchmark_symbol: str = "000300.SH") -> dict[str, object]:
    start = date(2026, 1, 5)
    return {
        "equity_curve": [100.0, 101.0, 102.0, 103.0, 104.0],
        "equity_dates": [(start + timedelta(days=index)).isoformat() for index in range(5)],
        "portfolio": {"benchmark_symbol": benchmark_symbol},
    }


def _service(
    *,
    context: dict[str, object] | None,
    benchmark_service: object | None = None,
    benchmark_metrics_service: object | None = None,
    fama_french_service: object | None = None,
) -> PortfolioLedgerAnalyticsService:
    return PortfolioLedgerAnalyticsService(
        _LedgerService(context),  # type: ignore[arg-type]
        benchmark_service=benchmark_service,  # type: ignore[arg-type]
        benchmark_metrics_service=benchmark_metrics_service,  # type: ignore[arg-type]
        fama_french_service=fama_french_service,  # type: ignore[arg-type]
    )


def _request(
    benchmark_id: str | None = None,
    *,
    market_returns: list[float] | None = None,
    smb_returns: list[float] | None = None,
    hml_returns: list[float] | None = None,
) -> PortfolioLedgerFamaFrenchRequest:
    return PortfolioLedgerFamaFrenchRequest(
        benchmark_id=benchmark_id,
        market_returns=market_returns,
        smb_returns=smb_returns if smb_returns is not None else [0.01, 0.02, 0.03, 0.04],
        hml_returns=hml_returns if hml_returns is not None else [-0.01, 0.00, 0.01, 0.02],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "request_benchmark_id",
        "portfolio_benchmark_symbol",
        "expected_benchmark_id",
        "expected_reason",
    ),
    [
        ("hs300", "000300.SH", "hs300", "fama_french_dated_alignment_required"),
        ("csi500", "000300.SH", "csi500", "fama_french_dated_alignment_required"),
        ("csi800", "000300.SH", "csi800", "fama_french_dated_alignment_required"),
        ("000300.SH", "000300.SH", "hs300", "fama_french_dated_alignment_required"),
        ("000905.SH", "000300.SH", "csi500", "fama_french_dated_alignment_required"),
        ("000906.SH", "000300.SH", "csi800", "fama_french_dated_alignment_required"),
        (None, "000905.SH", "csi500", "fama_french_dated_alignment_required"),
        ("spx", "000300.SH", "spx", "benchmark_unsupported_by_opendata"),
        ("btc", "000300.SH", "btc", "benchmark_unsupported_by_opendata"),
        ("unknown", "000300.SH", "unknown", "benchmark_unsupported_by_opendata"),
    ],
)
@pytest.mark.parametrize("market_returns", [None, [0.01, 0.02, 0.03, 0.04]])
@pytest.mark.parametrize(
    ("smb_returns", "hml_returns"),
    [
        ([0.01, 0.02, 0.03, 0.04], [-0.01, 0.00, 0.01, 0.02]),
        ([0.11, 0.12], [-0.11, -0.12]),
    ],
)
async def test_opendata_mode_fails_closed_before_provider_or_regression(
    monkeypatch: pytest.MonkeyPatch,
    request_benchmark_id: str | None,
    portfolio_benchmark_symbol: str,
    expected_benchmark_id: str,
    expected_reason: str,
    market_returns: list[float] | None,
    smb_returns: list[float],
    hml_returns: list[float],
) -> None:
    monkeypatch.setattr(
        portfolio_ledger_analytics,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True),
    )
    benchmark_service = SimpleNamespace(get_benchmark_returns=AsyncMock())
    benchmark_metrics_service = SimpleNamespace(returns_from_equity_curve=Mock())
    fama_french_service = SimpleNamespace(calculate=Mock())
    ledger_service = _LedgerService(_context(benchmark_symbol=portfolio_benchmark_symbol))
    service = PortfolioLedgerAnalyticsService(
        ledger_service,  # type: ignore[arg-type]
        benchmark_service=benchmark_service,
        benchmark_metrics_service=benchmark_metrics_service,
        fama_french_service=fama_french_service,
    )

    result = await service.calculate_fama_french(
        "user-1",
        "portfolio-1",
        _request(
            request_benchmark_id,
            market_returns=market_returns,
            smb_returns=smb_returns,
            hml_returns=hml_returns,
        ),
    )

    ledger_service.analytics_context.assert_awaited_once_with("user-1", "portfolio-1")
    assert result is not None
    assert result.status == "degraded"
    assert result.benchmark_id == expected_benchmark_id
    assert result.reason == expected_reason
    assert result.observation_count == 0
    assert result.alpha is None
    assert result.market_beta is None
    assert result.smb_beta is None
    assert result.hml_beta is None
    assert result.r_squared is None
    benchmark_service.get_benchmark_returns.assert_not_awaited()
    benchmark_metrics_service.returns_from_equity_curve.assert_not_called()
    fama_french_service.calculate.assert_not_called()


@pytest.mark.asyncio
async def test_opendata_mode_returns_not_found_before_benchmark_or_regression(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portfolio_ledger_analytics,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=True),
    )
    benchmark_service = SimpleNamespace(get_benchmark_returns=AsyncMock())
    benchmark_metrics_service = SimpleNamespace(returns_from_equity_curve=Mock())
    fama_french_service = SimpleNamespace(calculate=Mock())
    ledger_service = _LedgerService(None)
    service = PortfolioLedgerAnalyticsService(
        ledger_service,  # type: ignore[arg-type]
        benchmark_service=benchmark_service,
        benchmark_metrics_service=benchmark_metrics_service,
        fama_french_service=fama_french_service,
    )

    result = await service.calculate_fama_french("user-1", "missing", _request())

    ledger_service.analytics_context.assert_awaited_once_with("user-1", "missing")
    assert result is None
    benchmark_service.get_benchmark_returns.assert_not_awaited()
    benchmark_metrics_service.returns_from_equity_curve.assert_not_called()
    fama_french_service.calculate.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_opendata_guard_preserves_legacy_benchmark_and_regression_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portfolio_ledger_analytics,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=False),
    )
    benchmark_service = SimpleNamespace(
        get_benchmark_returns=AsyncMock(
            return_value=SimpleNamespace(status="ok", returns=[0.01, 0.02, 0.03, 0.04])
        )
    )
    benchmark_metrics_service = SimpleNamespace(
        returns_from_equity_curve=Mock(return_value=[0.02, 0.03, 0.04, 0.05])
    )
    fama_french_service = SimpleNamespace(
        calculate=Mock(
            return_value=SimpleNamespace(
                status="ok",
                observation_count=4,
                alpha=0.001,
                market_beta=0.8,
                smb_beta=0.2,
                hml_beta=-0.1,
                r_squared=0.9,
                reason=None,
            )
        )
    )
    service = _service(
        context=_context(),
        benchmark_service=benchmark_service,
        benchmark_metrics_service=benchmark_metrics_service,
        fama_french_service=fama_french_service,
    )

    result = await service.calculate_fama_french("user-1", "portfolio-1", _request())

    assert result is not None
    assert result.status == "ok"
    assert result.benchmark_id == "hs300"
    assert result.market_beta == 0.8
    benchmark_service.get_benchmark_returns.assert_awaited_once_with(
        "hs300", "2026-01-05", "2026-01-09"
    )
    fama_french_service.calculate.assert_called_once()


@pytest.mark.asyncio
async def test_disabled_opendata_guard_preserves_user_supplied_market_returns_without_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        portfolio_ledger_analytics,
        "get_settings",
        lambda: SimpleNamespace(MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED=False),
    )
    benchmark_service = SimpleNamespace(get_benchmark_returns=AsyncMock())
    benchmark_metrics_service = SimpleNamespace(
        returns_from_equity_curve=Mock(return_value=[0.02, 0.03, 0.04, 0.05])
    )
    fama_french_service = SimpleNamespace(
        calculate=Mock(
            return_value=SimpleNamespace(
                status="ok",
                observation_count=4,
                alpha=0.001,
                market_beta=0.8,
                smb_beta=0.2,
                hml_beta=-0.1,
                r_squared=0.9,
                reason=None,
            )
        )
    )
    service = _service(
        context=_context(),
        benchmark_service=benchmark_service,
        benchmark_metrics_service=benchmark_metrics_service,
        fama_french_service=fama_french_service,
    )

    result = await service.calculate_fama_french(
        "user-1",
        "portfolio-1",
        _request(market_returns=[0.01, 0.02, 0.03, 0.04]),
    )

    assert result is not None
    assert result.status == "ok"
    benchmark_service.get_benchmark_returns.assert_not_awaited()
    fama_french_service.calculate.assert_called_once()
