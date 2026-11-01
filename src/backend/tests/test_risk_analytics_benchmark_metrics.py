from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.api.risk_analytics import get_backtest_service, get_benchmark_service
from app.schemas.backtest import BacktestResult, TaskStatus
from app.schemas.risk_analytics import BenchmarkReturnObservation, BenchmarkReturnsResult
from tests.conftest import app, register_and_login


def _backtest_result() -> BacktestResult:
    return BacktestResult(
        task_id="task123",
        strategy_id="strategy1",
        symbol="000001.SZ",
        start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2024, 1, 6, tzinfo=timezone.utc),
        status=TaskStatus.COMPLETED,
        equity_curve=[100.0, 102.0, 101.0, 104.0, 103.0, 106.0],
        equity_dates=[
            "2024-01-01 00:00:00",
            "2024-01-02 00:00:00",
            "2024-01-03 00:00:00",
            "2024-01-04 00:00:00",
            "2024-01-05 00:00:00",
            "2024-01-06 00:00:00",
        ],
        created_at=datetime(2024, 1, 6, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_benchmark_metrics_service_omits_annualized_metrics_without_frequency_proof():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    intervals = [
        ("2024-01-01", "2024-01-02"),
        ("2024-01-02", "2024-01-03"),
        ("2024-01-03", "2024-01-04"),
        ("2024-01-04", "2024-01-05"),
        ("2024-01-05", "2024-01-06"),
    ]
    result = BenchmarkMetricsService().calculate(
        strategy_return_observations=[
            BenchmarkReturnObservation(
                start_date=start_date,
                end_date=end_date,
                return_value=value,
            )
            for (start_date, end_date), value in zip(
                intervals,
                [0.02, -0.009804, 0.029703, -0.009615, 0.029126],
                strict=True,
            )
        ],
        benchmark_return_observations=[
            BenchmarkReturnObservation(
                start_date=start_date,
                end_date=end_date,
                return_value=value,
            )
            for (start_date, end_date), value in zip(
                intervals,
                [0.01, -0.00495, 0.014925, -0.004902, 0.014778],
                strict=True,
            )
        ],
        benchmark_id="hs300",
        risk_free_rate=0.0,
    )

    assert result.status == "degraded"
    assert result.benchmark_id == "hs300"
    assert result.observation_count == 5
    assert result.beta > 1.0
    assert result.reason == "annualization_periodicity_unknown"
    assert result.alpha is None
    assert result.tracking_error is None
    assert result.information_ratio is None


@pytest.mark.asyncio
async def test_benchmark_metrics_service_returns_degraded_for_insufficient_overlap():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    result = BenchmarkMetricsService().calculate(
        benchmark_id="hs300",
        strategy_return_observations=[
            BenchmarkReturnObservation(
                start_date="2024-01-01",
                end_date="2024-01-02",
                return_value=0.01,
            )
        ],
        benchmark_return_observations=[
            BenchmarkReturnObservation(
                start_date="2024-01-01",
                end_date="2024-01-02",
                return_value=0.01,
            )
        ],
    )

    assert result.status == "degraded"
    assert result.reason == "insufficient_overlap"
    assert result.observation_count == 1


@pytest.mark.asyncio
async def test_benchmark_metrics_service_fails_closed_without_interval_metadata():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    result = BenchmarkMetricsService().calculate(
        strategy_returns=[0.01, 0.02, -0.01],
        benchmark_returns=[0.03, -0.01, 0.02],
        benchmark_id="hs300",
    )

    assert result.status == "degraded"
    assert result.reason == "missing_return_intervals"
    assert result.observation_count == 0


@pytest.mark.asyncio
async def test_benchmark_metrics_service_matches_complete_intervals_not_end_dates():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    strategy = [
        ("2024-01-01", "2024-01-02", 0.01),
        ("2024-01-02", "2024-01-03", 0.02),
        ("2024-01-03", "2024-01-04", -0.01),
        ("2024-01-04", "2024-01-05", 0.03),
        ("2024-01-05", "2024-01-06", 0.01),
    ]
    benchmark = [
        # Same end date as strategy's second interval, but a different start.
        ("2024-01-01", "2024-01-03", 0.015),
        ("2024-01-03", "2024-01-04", -0.005),
        ("2024-01-04", "2024-01-05", 0.01),
        ("2024-01-05", "2024-01-06", 0.006),
    ]
    result = BenchmarkMetricsService().calculate(
        strategy_return_observations=[
            BenchmarkReturnObservation(
                start_date=start_date,
                end_date=end_date,
                return_value=value,
            )
            for start_date, end_date, value in strategy
        ],
        benchmark_return_observations=[
            BenchmarkReturnObservation(
                start_date=start_date,
                end_date=end_date,
                return_value=value,
            )
            for start_date, end_date, value in benchmark
        ],
        benchmark_id="hs300",
    )

    assert result.status == "degraded"
    assert result.observation_count == 3
    assert result.reason == "annualization_periodicity_unknown"
    assert result.beta is not None


@pytest.mark.asyncio
async def test_benchmark_metrics_service_rejects_nonfinite_or_out_of_range_risk_free_rate():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    for risk_free_rate in (float("nan"), float("inf"), -1.01, 1.01):
        result = BenchmarkMetricsService().calculate(
            benchmark_id="hs300",
            strategy_return_observations=[],
            benchmark_return_observations=[],
            risk_free_rate=risk_free_rate,
        )

        assert result.status == "degraded"
        assert result.reason == "invalid_risk_free_rate"
        assert result.risk_free_rate == 0.0


@pytest.mark.asyncio
async def test_equity_curve_returns_keep_exact_adjacent_date_intervals():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    observations = BenchmarkMetricsService.return_observations_from_equity_curve(
        [100.0, 110.0, 121.0],
        ["2024-01-01", "2024-01-03", "2024-01-04"],
    )

    assert [(item.start_date, item.end_date) for item in observations] == [
        ("2024-01-01", "2024-01-03"),
        ("2024-01-03", "2024-01-04"),
    ]


def test_equity_curve_dates_normalize_valid_timestamps_without_timezone_conversion():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    observations = BenchmarkMetricsService.return_observations_from_equity_curve(
        [100.0, 110.0, 121.0],
        [
            "2024-01-01 00:00:00",
            "2024-01-02T00:30:00+14:00",
            "2024-01-03T00:00:00Z",
        ],
    )

    assert [(item.start_date, item.end_date) for item in observations] == [
        ("2024-01-01", "2024-01-02"),
        ("2024-01-02", "2024-01-03"),
    ]


@pytest.mark.asyncio
async def test_equity_curve_returns_fail_closed_for_missing_or_out_of_order_dates():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    with pytest.raises(ValueError, match="invalid_strategy_return_dates"):
        BenchmarkMetricsService.return_observations_from_equity_curve(
            [100.0, 110.0], ["2024-01-01"]
        )

    with pytest.raises(ValueError, match="invalid_strategy_return_dates"):
        BenchmarkMetricsService.return_observations_from_equity_curve(
            [100.0, 110.0], ["2024-01-02", "2024-01-01"]
        )


@pytest.mark.asyncio
async def test_equity_curve_returns_reject_duplicate_dates_without_proven_order():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    with pytest.raises(ValueError, match="invalid_strategy_return_dates"):
        BenchmarkMetricsService.return_observations_from_equity_curve(
            [100.0, 105.0, 110.0],
            [
                "2024-01-01 00:00:00",
                "2024-01-01T23:59:00-12:00",
                "2024-01-02",
            ],
        )


def test_equity_curve_returns_fail_closed_for_nonpositive_or_nonfinite_nav():
    from app.services.risk_analytics.benchmark_metrics import BenchmarkMetricsService

    for nav in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="invalid_strategy_nav_values"):
            BenchmarkMetricsService.return_observations_from_equity_curve(
                [100.0, nav, 110.0],
                ["2024-01-01", "2024-01-02", "2024-01-03"],
            )


@pytest.mark.asyncio
async def test_benchmark_metrics_api_requires_auth(client: AsyncClient):
    response = await client.get(
        "/api/v1/risk-analytics/benchmark-metrics/task123?benchmark_id=hs300"
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_benchmark_metrics_api_returns_metrics_for_backtest(client: AsyncClient):
    _, headers = await register_and_login(client, username="risk_benchmark_metrics_user")
    mock_backtest_service = SimpleNamespace(get_result=AsyncMock(return_value=_backtest_result()))

    class FakeBenchmarkService:
        requested_dates: list[tuple[str, str]] = []

        async def get_benchmark_returns(self, benchmark_id: str, start_date: str, end_date: str):
            self.requested_dates.append((start_date, end_date))
            return BenchmarkReturnsResult(
                status="ok",
                benchmark_id=benchmark_id,
                symbol="000300.SH",
                start_date=start_date,
                end_date=end_date,
                observation_count=6,
                dates=[
                    "2024-01-01",
                    "2024-01-02",
                    "2024-01-03",
                    "2024-01-04",
                    "2024-01-05",
                    "2024-01-06",
                ],
                returns=[0.01, -0.00495, 0.014925, -0.004902, 0.014778],
                return_observations=[
                    BenchmarkReturnObservation(
                        start_date=start_date,
                        end_date=end_date,
                        return_value=value,
                    )
                    for (start_date, end_date), value in zip(
                        [
                            ("2024-01-01", "2024-01-02"),
                            ("2024-01-02", "2024-01-03"),
                            ("2024-01-03", "2024-01-04"),
                            ("2024-01-04", "2024-01-05"),
                            ("2024-01-05", "2024-01-06"),
                        ],
                        [0.01, -0.00495, 0.014925, -0.004902, 0.014778],
                        strict=True,
                    )
                ],
            )

    app.dependency_overrides[get_backtest_service] = lambda: mock_backtest_service
    app.dependency_overrides[get_benchmark_service] = lambda: FakeBenchmarkService()
    try:
        response = await client.get(
            "/api/v1/risk-analytics/benchmark-metrics/task123?benchmark_id=hs300",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_backtest_service, None)
        app.dependency_overrides.pop(get_benchmark_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["backtest_id"] == "task123"
    assert payload["benchmark_id"] == "hs300"
    assert payload["status"] == "degraded"
    assert payload["observation_count"] == 5
    assert payload["beta"] > 1.0
    assert payload["reason"] == "annualization_periodicity_unknown"
    assert payload["alpha"] is None
    assert payload["tracking_error"] is None
    assert payload["information_ratio"] is None
    assert FakeBenchmarkService.requested_dates == [("2024-01-01", "2024-01-06")]
