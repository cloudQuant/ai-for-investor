"""The scheduled hourly crypto task must stay current first and only page history on request.

Why this file exists: on 2026-11-05..07 the armed hourly task produced 52 consecutive
`Script call timed out after 600 seconds` failures and wrote nothing, because `fetch_data` paged
the whole hourly history from 2020 (about sixty REST pages per symbol) *before* the cheap tail
refresh, so the per-run budget expired first. These tests pin the order and the default so the
shape cannot come back: the tail is cheap and always runs, backfill is opt-in, and one failing
symbol does not stop the rest.
"""

from __future__ import annotations

import logging

import pytest

pytest.importorskip("pandas", reason="optional pandas package is required")
pytest.importorskip("akshare", reason="optional akshare provider package is required")
pytest.importorskip("mysql.connector", reason="optional MySQL connector package is required")

from app.data_fetch.scripts.cryptos.hourly.crypto_hourly_market import (  # noqa: E402
    CryptoHourlyMarket,
)


class RecordingMarket(CryptoHourlyMarket):
    """A CryptoHourlyMarket whose two I/O paths record their calls instead of touching a DB."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.logger = logging.getLogger("test.crypto_hourly")
        self._fail_on = fail_on or set()

    def refresh_tail(self, symbol: str, *, days: int = 3) -> int:
        self.calls.append(("tail", symbol))
        if symbol in self._fail_on:
            raise RuntimeError("tail source unavailable")
        return 1

    def backfill_history(self, symbol: str, *, start, end=None, source: str = "rest") -> int:
        self.calls.append(("backfill", symbol))
        return 100


def test_default_run_refreshes_the_tail_and_never_pages_history() -> None:
    market = RecordingMarket()
    frame = market.fetch_data(symbols=["btcusdt", "ethusdt"])

    assert market.calls == [("tail", "BTCUSDT"), ("tail", "ETHUSDT")]
    assert list(frame["symbol"]) == ["BTCUSDT", "ETHUSDT"]


def test_tail_runs_before_backfill_when_backfill_is_requested() -> None:
    market = RecordingMarket()
    market.fetch_data(symbols=["btcusdt"], backfill=True)

    assert market.calls == [("tail", "BTCUSDT"), ("backfill", "BTCUSDT")]


def test_one_failing_symbol_does_not_stop_the_others() -> None:
    market = RecordingMarket(fail_on={"ETHUSDT"})
    market.fetch_data(symbols=["btcusdt", "ethusdt", "solusdt"])

    assert market.calls == [
        ("tail", "BTCUSDT"),
        ("tail", "ETHUSDT"),
        ("tail", "SOLUSDT"),
    ], "every symbol must be attempted even when one raises"


def test_the_docstring_states_the_order_and_the_reason() -> None:
    doc = CryptoHourlyMarket.fetch_data.__doc__ or ""

    assert "tail" in doc.lower()
    assert "600" in doc, "the budget that the old shape blew must be named where the order is set"
