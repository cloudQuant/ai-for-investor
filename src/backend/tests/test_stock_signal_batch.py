"""After-close batch scheduling contracts without live provider calls."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.services.stock_signal.batch import Sse50SignalBatchRunner
from app.services.stock_signal.decision_policy import SignalPolicy
from app.services.stock_signal.quality import DataQualityGate
from app.services.stock_signal.universe import (
    Sse50UniverseMemberEvidence,
    Sse50UniversePITSnapshot,
)


class _Calendar:
    async def is_trading_day(self, value: date) -> bool:
        return value in {date(2026, 7, 29), date(2026, 7, 30)}

    async def next_trading_day(self, value: date) -> date:
        return value + timedelta(days=1)


class _Universe:
    def __init__(self, snapshot: Sse50UniversePITSnapshot | None = None) -> None:
        self.snapshot = snapshot or _pit_snapshot()
        self.requested_as_of: date | None = None
        self.requested_cutoff: datetime | None = None

    async def resolve_pit(
        self, *, as_of_date: date, known_by: datetime
    ) -> Sse50UniversePITSnapshot:
        self.requested_as_of = as_of_date
        self.requested_cutoff = known_by
        return self.snapshot


class _CurrentOnlyUniverse:
    source = "fixture.current_only"

    def __init__(self) -> None:
        self.calls = 0

    async def members(self) -> list[dict[str, str]]:
        self.calls += 1
        return _current_members()


def _current_members() -> list[dict[str, str]]:
    return [{"symbol": f"{600000 + index:06d}.SH", "name": f"测试{index}"} for index in range(50)]


def _pit_snapshot(
    *,
    valid_from: date = date(2020, 1, 1),
    valid_to: date | None = None,
    available_at: datetime = datetime(2019, 12, 20, tzinfo=timezone.utc),
) -> Sse50UniversePITSnapshot:
    return Sse50UniversePITSnapshot(
        source="fixture.sse50.history",
        snapshot_version="2026-07-30-r1",
        evidence_ref="fixture:sse50:2026-07-30",
        members=tuple(
            Sse50UniverseMemberEvidence(
                symbol=f"{600000 + index:06d}.SH",
                name=f"测试{index}",
                valid_from=valid_from,
                valid_to=valid_to,
                published_at=datetime(2019, 12, 19, tzinfo=timezone.utc),
                platform_available_at=available_at,
                evidence_ref=f"fixture:member:{600000 + index:06d}",
            )
            for index in range(50)
        ),
    )


def _configured_runner(*, universe: Any | None = None) -> Sse50SignalBatchRunner:
    runner = Sse50SignalBatchRunner(calendar=_Calendar(), universe=universe or _Universe())
    runner.settings = SimpleNamespace(
        STOCK_SIGNAL_ROUND_TRIP_COST_BPS=20.0,
        STOCK_SIGNAL_BUY_SUCCESS_THRESHOLD_BPS=30.0,
        STOCK_SIGNAL_SELL_SUCCESS_THRESHOLD_BPS=30.0,
        STOCK_SIGNAL_MAX_CONCURRENCY=2,
        STOCK_SIGNAL_MIN_HISTORY_BARS=60,
        STOCK_SIGNAL_MAX_FINANCIAL_AGE_DAYS=210,
        STOCK_SIGNAL_MAX_NEWS_AGE_DAYS=7,
        STOCK_SIGNAL_SCHEDULE_TIMEZONE="Asia/Shanghai",
    )
    runner.policy = SignalPolicy(
        round_trip_cost_bps=20.0,
        buy_success_threshold_bps=30.0,
        sell_success_threshold_bps=30.0,
    )
    runner.quality_gate = DataQualityGate()
    return runner


def _freeze_batch_clock(
    monkeypatch: pytest.MonkeyPatch,
    business_day: date,
    *,
    hour: int = 19,
    minute: int = 10,
) -> None:
    from app.services.stock_signal import batch as batch_module

    local_now = datetime(
        business_day.year,
        business_day.month,
        business_day.day,
        hour,
        minute,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    monkeypatch.setattr(batch_module, "_shanghai_today", lambda: business_day)
    monkeypatch.setattr(batch_module, "_now", lambda: local_now.astimezone(timezone.utc))


@pytest.mark.asyncio
async def test_batch_claims_one_idempotent_run_and_records_all_member_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_batch_clock(monkeypatch, date(2026, 7, 30))
    runner = _configured_runner()
    calls: list[str] = []

    async def process_member(
        *, member: dict[str, str], **_kwargs: object
    ) -> tuple[str, str | None]:
        calls.append(member["symbol"])
        return ("eligible" if member["symbol"] == "600000.SH" else "degraded", None)

    monkeypatch.setattr(runner, "_process_member", process_member)

    first = await runner.run(as_of_date=date(2026, 7, 30))
    second = await runner.run(as_of_date=date(2026, 7, 30))

    assert first is not None
    assert first.status == "completed"
    assert first.expected_count == 50
    assert first.created_count == 50
    assert first.eligible_count == 1
    assert first.degraded_count == 49
    assert second is not None
    assert second.id == first.id
    assert set(calls) == {member["symbol"] for member in _current_members()}
    assert first.config_snapshot_json["universe"]["point_in_time_status"] == "PROVIDER_ATTESTED"


@pytest.mark.asyncio
async def test_batch_refuses_non_trading_dates_without_inferring_weekdays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_batch_clock(monkeypatch, date(2026, 8, 1))
    runner = _configured_runner()

    result = await runner.run(as_of_date=date(2026, 8, 1))

    assert result is None


@pytest.mark.asyncio
async def test_second_worker_does_not_process_a_run_already_claimed_by_another_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_batch_clock(monkeypatch, date(2026, 7, 30))
    runner = _configured_runner()
    universe = await runner._resolve_universe(
        date(2026, 7, 30), current_business_date=date(2026, 7, 30)
    )
    claimed, did_claim = await runner._claim_run(date(2026, 7, 30), universe)

    async def process_member(**_kwargs: object) -> tuple[str, str | None]:
        raise AssertionError("a second worker must not process an already-running batch")

    monkeypatch.setattr(runner, "_process_member", process_member)
    returned = await runner.run(as_of_date=date(2026, 7, 30))

    assert did_claim is True
    assert returned is not None
    assert returned.id == claimed.id
    assert returned.status == "running"


@pytest.mark.asyncio
async def test_current_only_provider_cannot_resolve_a_historical_signal_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_batch_clock(monkeypatch, date(2026, 7, 30))
    current_only = _CurrentOnlyUniverse()
    runner = _configured_runner(universe=current_only)

    with pytest.raises(RuntimeError, match="historical_sse50_signal_replay_unavailable"):
        await runner.run(as_of_date=date(2026, 7, 29))

    assert current_only.calls == 0


@pytest.mark.asyncio
async def test_injected_pit_provider_cannot_enable_historical_signal_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _freeze_batch_clock(monkeypatch, date(2026, 7, 30))
    provider = _Universe()
    runner = _configured_runner(universe=provider)

    with pytest.raises(RuntimeError, match="historical_sse50_signal_replay_unavailable"):
        await runner.run(as_of_date=date(2026, 7, 29))

    assert provider.requested_as_of is None


@pytest.mark.asyncio
async def test_default_current_only_batch_records_unverified_current_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business_today = date(2026, 7, 30)
    _freeze_batch_clock(monkeypatch, business_today)
    runner = _configured_runner(universe=_CurrentOnlyUniverse())

    async def process_member(**_kwargs: object) -> tuple[str, str | None]:
        return "degraded", None

    monkeypatch.setattr(runner, "_process_member", process_member)
    result = await runner.run()

    assert result is not None
    assert result.config_snapshot_json["universe"]["temporal_scope"] == "current_only"
    assert result.config_snapshot_json["universe"]["point_in_time_status"] == "UNVERIFIED"
    assert "valid_from" not in result.config_snapshot_json["universe"]


@pytest.mark.asyncio
async def test_current_only_batch_is_rejected_before_shanghai_decision_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    business_today = date(2026, 7, 30)
    _freeze_batch_clock(monkeypatch, business_today, hour=19, minute=9)
    current_only = _CurrentOnlyUniverse()
    runner = _configured_runner(universe=current_only)

    with pytest.raises(RuntimeError, match="stock_signal_decision_cutoff_not_reached"):
        await runner.run()

    assert current_only.calls == 0


@pytest.mark.asyncio
async def test_pit_provider_must_cover_target_date_for_every_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = date(2026, 7, 30)
    _freeze_batch_clock(monkeypatch, target)
    items = list(_pit_snapshot().members)
    items[-1] = replace(items[-1], valid_to=target)
    provider = _Universe(replace(_pit_snapshot(), members=tuple(items)))
    runner = _configured_runner(universe=provider)

    with pytest.raises(RuntimeError, match="sse50_universe_pit_validity_gap"):
        await runner._resolve_universe(target, current_business_date=target)


@pytest.mark.asyncio
async def test_pit_provider_rejects_membership_evidence_available_after_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = date(2026, 7, 30)
    cutoff = datetime(2026, 7, 30, 19, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    _freeze_batch_clock(monkeypatch, target)
    items = list(_pit_snapshot().members)
    items[-1] = replace(items[-1], platform_available_at=cutoff + timedelta(seconds=1))
    provider = _Universe(replace(_pit_snapshot(), members=tuple(items)))
    runner = _configured_runner(universe=provider)

    with pytest.raises(RuntimeError, match="sse50_universe_pit_evidence_after_cutoff"):
        await runner._resolve_universe(target, current_business_date=target)

    assert provider.requested_as_of == target
    assert provider.requested_cutoff == cutoff
