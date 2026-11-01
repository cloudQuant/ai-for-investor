"""Benchmark comparison metric calculations."""

import math
import statistics
from collections.abc import Sequence
from datetime import date, datetime

from app.schemas.risk_analytics import BenchmarkMetricsResult, BenchmarkReturnObservation


class BenchmarkMetricsService:
    """Calculate strategy performance metrics relative to a benchmark."""

    def calculate(
        self,
        *,
        benchmark_id: str,
        strategy_returns: list[float] | None = None,
        benchmark_returns: list[float] | None = None,
        strategy_return_observations: Sequence[BenchmarkReturnObservation] | None = None,
        benchmark_return_observations: Sequence[BenchmarkReturnObservation] | None = None,
        risk_free_rate: float = 0.0,
    ) -> BenchmarkMetricsResult:
        """Calculate beta from returns with identical date intervals.

        The float-only arguments remain accepted for callers on the old internal
        interface, but cannot be paired safely without interval metadata. Annualized
        metrics are omitted because matching interval endpoints alone does not prove
        that every observation has the same frequency.
        """
        del strategy_returns, benchmark_returns
        try:
            validated_risk_free_rate = float(risk_free_rate)
        except (TypeError, ValueError, OverflowError):
            validated_risk_free_rate = float("nan")
        if (
            not math.isfinite(validated_risk_free_rate)
            or not -1.0 <= validated_risk_free_rate <= 1.0
        ):
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=0,
                risk_free_rate=0.0,
                reason="invalid_risk_free_rate",
            )
        if strategy_return_observations is None or benchmark_return_observations is None:
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=0,
                risk_free_rate=validated_risk_free_rate,
                reason="missing_return_intervals",
            )

        strategy_by_interval, strategy_error = self._index_observations(
            strategy_return_observations
        )
        benchmark_by_interval, benchmark_error = self._index_observations(
            benchmark_return_observations
        )
        if strategy_error or benchmark_error:
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=0,
                risk_free_rate=validated_risk_free_rate,
                reason="invalid_return_intervals",
            )

        assert strategy_by_interval is not None
        assert benchmark_by_interval is not None
        common_intervals = sorted(strategy_by_interval.keys() & benchmark_by_interval.keys())
        strategy = [strategy_by_interval[interval] for interval in common_intervals]
        benchmark = [benchmark_by_interval[interval] for interval in common_intervals]
        count = len(common_intervals)
        if count < 2:
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=count,
                risk_free_rate=validated_risk_free_rate,
                reason="insufficient_overlap",
            )

        try:
            benchmark_variance = statistics.pvariance(benchmark)
            strategy_mean = statistics.fmean(strategy)
            benchmark_mean = statistics.fmean(benchmark)
            covariance = statistics.fmean(
                (strategy_value - strategy_mean) * (benchmark_value - benchmark_mean)
                for strategy_value, benchmark_value in zip(strategy, benchmark, strict=True)
            )
        except OverflowError:
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=count,
                risk_free_rate=validated_risk_free_rate,
                reason="invalid_return_values",
            )
        if not math.isfinite(benchmark_variance):
            variance_reason = "invalid_return_values"
        elif benchmark_variance <= 0:
            variance_reason = "zero_benchmark_variance"
        else:
            variance_reason = None
        if variance_reason is not None:
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=count,
                risk_free_rate=validated_risk_free_rate,
                reason=variance_reason,
            )

        beta = covariance / benchmark_variance
        if not math.isfinite(beta):
            return BenchmarkMetricsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                observation_count=count,
                risk_free_rate=validated_risk_free_rate,
                reason="invalid_return_values",
            )
        return BenchmarkMetricsResult(
            status="degraded",
            benchmark_id=benchmark_id,
            observation_count=count,
            beta=round(beta, 6),
            risk_free_rate=round(validated_risk_free_rate, 6),
            reason="annualization_periodicity_unknown",
        )

    @staticmethod
    def _index_observations(
        observations: Sequence[BenchmarkReturnObservation],
    ) -> tuple[dict[tuple[str, str], float] | None, bool]:
        indexed: dict[tuple[str, str], float] = {}
        previous_end_date: str | None = None
        for observation in observations:
            start_date = observation.start_date
            end_date = observation.end_date
            try:
                start = date.fromisoformat(start_date)
                end = date.fromisoformat(end_date)
                value = float(observation.return_value)
            except (TypeError, ValueError):
                return None, True
            if (
                start.isoformat() != start_date
                or end.isoformat() != end_date
                or start >= end
                or not math.isfinite(value)
                or (previous_end_date is not None and start_date < previous_end_date)
            ):
                return None, True

            interval = (start_date, end_date)
            if interval in indexed:
                return None, True
            indexed[interval] = value
            previous_end_date = end_date
        return indexed, False

    @staticmethod
    def returns_from_equity_curve(equity_curve: list[float]) -> list[float]:
        """Calculate close-to-close returns from an equity curve."""
        returns: list[float] = []
        values = [float(value) for value in equity_curve if math.isfinite(float(value))]
        for previous, current in zip(values, values[1:], strict=False):
            if previous > 0:
                returns.append((current - previous) / previous)
        return returns

    @staticmethod
    def return_observations_from_equity_curve(
        equity_curve: Sequence[float],
        equity_dates: Sequence[str],
    ) -> list[BenchmarkReturnObservation]:
        """Calculate dated returns from a strictly ordered, unique-date equity curve."""
        if len(equity_curve) != len(equity_dates):
            raise ValueError("invalid_strategy_return_dates")

        normalized_dates: list[str] = []
        values: list[float] = []
        previous_date: date | None = None
        for raw_date, raw_value in zip(equity_dates, equity_curve, strict=True):
            parsed_date = BenchmarkMetricsService._parse_equity_business_date(raw_date)
            try:
                value = float(raw_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("invalid_strategy_nav_values") from exc
            if previous_date is not None and parsed_date <= previous_date:
                raise ValueError("invalid_strategy_return_dates")
            if not math.isfinite(value) or value <= 0:
                raise ValueError("invalid_strategy_nav_values")
            normalized_dates.append(parsed_date.isoformat())
            values.append(value)
            previous_date = parsed_date

        observations: list[BenchmarkReturnObservation] = []
        for index in range(1, len(values)):
            previous = values[index - 1]
            current = values[index]
            return_value = (current - previous) / previous
            if not math.isfinite(return_value):
                raise ValueError("invalid_strategy_return_values")
            observations.append(
                BenchmarkReturnObservation(
                    start_date=normalized_dates[index - 1],
                    end_date=normalized_dates[index],
                    return_value=return_value,
                )
            )
        return observations

    @staticmethod
    def _parse_equity_business_date(raw_date: str) -> date:
        """Parse a date or timestamp without converting its written business date.

        For timezone-aware timestamps, the date explicitly written in the source
        string is retained. The offset is validated but never converted to UTC or
        another timezone because that could change the business date.
        """
        date_text = str(raw_date).strip()
        try:
            if len(date_text) == 10:
                parsed_date = date.fromisoformat(date_text)
                if parsed_date.isoformat() == date_text:
                    return parsed_date
                raise ValueError("invalid_strategy_return_dates")

            if len(date_text) < 11 or date_text[10] not in {"T", " "}:
                raise ValueError("invalid_strategy_return_dates")
            parsed_prefix = date.fromisoformat(date_text[:10])
            if parsed_prefix.isoformat() != date_text[:10]:
                raise ValueError("invalid_strategy_return_dates")
            datetime_text = date_text[:-1] + "+00:00" if date_text.endswith("Z") else date_text
            parsed_datetime = datetime.fromisoformat(datetime_text)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("invalid_strategy_return_dates") from exc
        if parsed_datetime.date() != parsed_prefix:
            raise ValueError("invalid_strategy_return_dates")
        return parsed_prefix
