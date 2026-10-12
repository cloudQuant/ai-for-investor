"""Verify calendar event grids against their declared coverage windows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        EventKey,
        MarketDataStore,
        MdCalendarSnapshot,
        TimeWindow,
    )


async def _calendar_event_keys(
    self: MarketDataStore,
    snapshot: MdCalendarSnapshot,
    coverage_window: TimeWindow,
    *,
    requested_window: TimeWindow,
    data_kind: str,
    frequency: str,
) -> tuple[EventKey, ...]:
    from app.services.market_data.store import (
        EventKey,
        MarketDataStoreError,
        MdCalendarEvent,
        _stored_utc,
        _window_intersection,
        calendar_coverage_descriptor,
        calendar_coverage_event_key,
        datetime,
        select,
    )

    event_window = _window_intersection(coverage_window, requested_window)
    await self._assert_calendar_grid_declared(
        snapshot,
        coverage_window,
        data_kind=data_kind,
        frequency=frequency,
    )
    rows = list(
        (
            await self._db.execute(
                select(MdCalendarEvent)
                .where(
                    MdCalendarEvent.calendar_snapshot_id == snapshot.id,
                    MdCalendarEvent.event_start.is_not(None),
                    MdCalendarEvent.event_start >= event_window.start_at,
                    MdCalendarEvent.event_start < event_window.end_at,
                )
                .order_by(MdCalendarEvent.event_start, MdCalendarEvent.id)
            )
        )
        .scalars()
        .all()
    )
    event_keys: list[EventKey] = []
    seen: set[datetime] = set()
    for row in rows:
        if not row.is_trading_day or row.event_type != "session":
            if calendar_coverage_descriptor(row.event_payload_json) is not None:
                raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
            continue
        try:
            descriptor = calendar_coverage_descriptor(row.event_payload_json)
        except ValueError as exc:
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY") from exc
        if descriptor is None:
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        if descriptor != (data_kind, frequency):
            continue
        if row.event_start is None:
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        event_at = _stored_utc(row.event_start, field_name="calendar event_start")
        try:
            expected_coverage_key = calendar_coverage_event_key(
                event_start=event_at,
                data_kind=data_kind,
                frequency=frequency,
            )
        except ValueError as exc:
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY") from exc
        if row.coverage_event_key != expected_coverage_key:
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        if not coverage_window.contains(EventKey(event_at)):
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        if not event_window.contains(EventKey(event_at)):
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        if event_at in seen:
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        seen.add(event_at)
        event_keys.append(EventKey(event_at))
    return tuple(sorted(event_keys))


async def _assert_calendar_grid_declared(
    self: MarketDataStore,
    snapshot: MdCalendarSnapshot,
    coverage_window: TimeWindow,
    *,
    data_kind: str,
    frequency: str,
) -> None:
    """Prove a frequency grid exists without loading the whole snapshot.

    A holiday or weekend request can legitimately contain no expected
    event.  It is still known only if the snapshot declares the requested
    grid elsewhere.  The materialized coverage key gives that proof in one
    indexed, bounded witness query rather than scanning every event in a
    long-lived calendar segment.
    """
    from app.services.market_data.store import (
        EventKey,
        MarketDataStoreError,
        MdCalendarEvent,
        _stored_utc,
        calendar_coverage_descriptor,
        calendar_coverage_event_key,
        select,
    )

    key_prefix = f"{data_kind}:{frequency}@"
    witness = await self._db.scalar(
        select(MdCalendarEvent)
        .where(
            MdCalendarEvent.calendar_snapshot_id == snapshot.id,
            MdCalendarEvent.coverage_event_key.startswith(key_prefix, autoescape=True),
        )
        .order_by(MdCalendarEvent.event_start, MdCalendarEvent.id)
        .limit(1)
    )
    if witness is None:
        raise MarketDataStoreError("CALENDAR_GRID_UNAVAILABLE")
    if not witness.is_trading_day or witness.event_type != "session" or witness.event_start is None:
        raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
    try:
        descriptor = calendar_coverage_descriptor(witness.event_payload_json)
        event_at = _stored_utc(witness.event_start, field_name="calendar event_start")
        expected_coverage_key = calendar_coverage_event_key(
            event_start=event_at,
            data_kind=data_kind,
            frequency=frequency,
        )
    except ValueError as exc:
        raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY") from exc
    if (
        descriptor != (data_kind, frequency)
        or witness.coverage_event_key != expected_coverage_key
        or not coverage_window.contains(EventKey(event_at))
    ):
        raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
