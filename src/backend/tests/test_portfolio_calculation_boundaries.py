"""Failure-boundary checks for the portfolio calculation collaborators."""

from pathlib import Path

import pytest

from app.api.portfolio import api as portfolio_api
from app.api.portfolio.portfolio_common import _PortfolioSource
from app.services.valuation_types import PositionSpec


def _portfolio_source(*, status: str = "running") -> _PortfolioSource:
    return _PortfolioSource(
        id="instance-1",
        strategy_id="strategy-1",
        strategy_name="Strategy 1",
        status=status,
    )


def test_valued_source_positions_propagates_valuation_failure_before_metadata_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _portfolio_source()
    source.position_source = "snapshot"
    raw_position = {
        "data_name": "BTC-USDT-SWAP",
        "size": 2.0,
        "position_source": "snapshot",
    }
    error = RuntimeError("valuation backend unavailable")

    monkeypatch.setattr(portfolio_api, "_source_positions", lambda _source: [raw_position])
    monkeypatch.setattr(
        portfolio_api,
        "split_bidirectional_position_row",
        lambda row: [row],
    )
    monkeypatch.setattr(
        portfolio_api,
        "_contract_spec_for_position",
        lambda _symbol, _row, _source: PositionSpec(has_multiplier=True),
    )
    monkeypatch.setattr(
        portfolio_api,
        "_position_row_for_valuation",
        lambda row, _spec, *, position_source: row,
    )

    def raise_valuation_error(_row: dict[str, object], *, spec: PositionSpec | None = None) -> None:
        raise error

    monkeypatch.setattr(portfolio_api, "value_position", raise_valuation_error)

    with pytest.raises(RuntimeError, match="valuation backend unavailable") as raised:
        portfolio_api._valued_source_positions(source)

    assert raised.value is error
    assert raw_position == {
        "data_name": "BTC-USDT-SWAP",
        "size": 2.0,
        "position_source": "snapshot",
    }
    assert source.valuation_warnings == []
    assert source.asset_spec_source is None
    assert source.valuation_status == "empty"


def test_compact_workspace_overview_propagates_value_log_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _portfolio_source()
    source.snapshot = {"long_market_value": 100.0, "short_market_value": 0.0}
    source.log_dir = Path("/tmp/portfolio-value-log")
    error = OSError("value log could not be read")
    calls: list[tuple[Path | None, str | None]] = []

    def fail_summary(
        log_dir: Path | None,
        *,
        started_day: str | None = None,
    ) -> tuple[float, float, float] | None:
        calls.append((log_dir, started_day))
        raise error

    monkeypatch.setattr(portfolio_api, "_source_started_day", lambda _source: "2026-10-12")
    monkeypatch.setattr(portfolio_api, "_compact_value_log_summary", fail_summary)

    with pytest.raises(OSError, match="value log could not be read") as raised:
        portfolio_api._compact_workspace_overview([source])

    assert raised.value is error
    assert calls == [(source.log_dir, "2026-10-12")]
