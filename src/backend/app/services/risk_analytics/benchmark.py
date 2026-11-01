"""Benchmark data service for risk analytics."""

import math
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from app.config import get_settings
from app.schemas.risk_analytics import BenchmarkReturnObservation, BenchmarkReturnsResult
from app.services.realtime_data_service import RealTimeDataService

BenchmarkFetcher = Callable[[str, str, str], Awaitable[list[dict[str, Any]]]]

BENCHMARK_SYMBOLS: dict[str, str] = {
    "hs300": "000300.SH",
    "csi500": "000905.SH",
    "csi800": "000906.SH",
    "spx": "SPX",
    "btc": "BTC/USDT",
}
_OPENDATA_RISK_BENCHMARK_IDS = frozenset({"hs300", "csi500", "csi800"})


class BenchmarkService:
    """Fetch benchmark prices and derive return series."""

    def __init__(self, data_fetcher: BenchmarkFetcher | None = None) -> None:
        self._uses_default_fetcher = data_fetcher is None
        self.data_fetcher = data_fetcher if data_fetcher is not None else self._default_fetcher

    async def get_benchmark_returns(
        self,
        benchmark_id: str,
        start_date: str,
        end_date: str,
        *,
        data_fetcher: BenchmarkFetcher | None = None,
    ) -> BenchmarkReturnsResult:
        """Fetch benchmark data and calculate close-to-close returns."""
        symbol = BENCHMARK_SYMBOLS.get(benchmark_id)
        if symbol is None:
            return BenchmarkReturnsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                start_date=start_date,
                end_date=end_date,
                reason="unknown_benchmark",
            )

        if (
            data_fetcher is None
            and self._uses_default_fetcher
            and benchmark_id in _OPENDATA_RISK_BENCHMARK_IDS
            and get_settings().MARKET_DATA_RISK_BENCHMARK_OPENDATA_ENABLED
        ):
            return BenchmarkReturnsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                reason="opendata_benchmark_consumer_not_migrated",
            )

        fetcher = data_fetcher if data_fetcher is not None else self.data_fetcher
        records = await fetcher(symbol, start_date, end_date)
        dates: list[str] = []
        closes: list[float] = []
        for record in records:
            close = record.get("close")
            record_date = record.get("date")
            if close is None or record_date is None:
                return BenchmarkReturnsResult(
                    status="degraded",
                    benchmark_id=benchmark_id,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    reason="invalid_benchmark_observation",
                )
            date_text = str(record_date)[:10]
            try:
                parsed_date = date.fromisoformat(date_text)
                close_value = float(close)
            except (OverflowError, TypeError, ValueError):
                return BenchmarkReturnsResult(
                    status="degraded",
                    benchmark_id=benchmark_id,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    reason="invalid_benchmark_observation",
                )
            if parsed_date.isoformat() != date_text or (dates and date_text <= dates[-1]):
                return BenchmarkReturnsResult(
                    status="degraded",
                    benchmark_id=benchmark_id,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    reason="invalid_benchmark_dates",
                )
            if not math.isfinite(close_value) or close_value <= 0:
                return BenchmarkReturnsResult(
                    status="degraded",
                    benchmark_id=benchmark_id,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    reason="invalid_benchmark_prices",
                )
            dates.append(date_text)
            closes.append(close_value)

        if len(closes) < 2:
            return BenchmarkReturnsResult(
                status="degraded",
                benchmark_id=benchmark_id,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                observation_count=len(closes),
                dates=dates,
                reason="insufficient_history",
            )

        returns: list[float] = []
        return_observations: list[BenchmarkReturnObservation] = []
        for index, (previous, current) in enumerate(zip(closes, closes[1:], strict=False)):
            return_value = round((current - previous) / previous, 6)
            if not math.isfinite(return_value):
                return BenchmarkReturnsResult(
                    status="degraded",
                    benchmark_id=benchmark_id,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    reason="invalid_benchmark_returns",
                )
            returns.append(return_value)
            return_observations.append(
                BenchmarkReturnObservation(
                    start_date=dates[index],
                    end_date=dates[index + 1],
                    return_value=return_value,
                )
            )
        return BenchmarkReturnsResult(
            status="ok",
            benchmark_id=benchmark_id,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            observation_count=len(closes),
            dates=dates,
            returns=returns,
            return_observations=return_observations,
        )

    @staticmethod
    async def _default_fetcher(symbol: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        service = RealTimeDataService()
        return await service.get_historical_data(
            "system",
            "benchmark",
            symbol,
            datetime.fromisoformat(start_date),
            datetime.fromisoformat(end_date),
            "1d",
        )
