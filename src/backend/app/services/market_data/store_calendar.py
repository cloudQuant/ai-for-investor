"""Read point-in-time calendar snapshots and project declared coverage."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.market_data.store import (
        CalendarSnapshot,
        CalendarTradingDayEvent,
        CalendarTradingDayEvents,
        EventKey,
        MarketDataStore,
        MarketDataVisibilityAnchor,
        MdCalendarSnapshot,
        ResolvedMarketDataQueryContext,
        Sequence,
        TimeWindow,
        datetime,
    )


async def read_calendar(
    self: MarketDataStore,
    *,
    calendar_code: str,
    window: TimeWindow,
    calendar_version: str | None = None,
    knowledge_cutoff: datetime | None = None,
    visibility_anchor: MarketDataVisibilityAnchor | None = None,
    data_kind: str = "bars",
    frequency: str = "1d",
    allowed_source_registry_ids: frozenset[str] | None = None,
) -> CalendarSnapshot:
    """Return one explicit calendar version or a typed unknown result.

    A calendar becomes ``KNOWN`` only when its persisted definition carries
    an explicit ``coverage_start_at``/``coverage_end_at`` pair (or the
    equivalent nested ``coverage_window`` mapping).  Weekdays, holidays,
    and missing sessions are never inferred by this reader.
    """
    from app.services.market_data.store import (
        PUBLICATION_CALENDAR_SNAPSHOT,
        CalendarSnapshot,
        CalendarStatus,
        MarketDataStoreError,
        MdCalendarSnapshot,
        MdPublication,
        TimeWindow,
        _calendar_coverage_window,
        _compose_calendar_segments,
        _composed_calendar_version,
        _is_visibility_sequence,
        _normalize_allowed_source_registry_ids,
        _publication_is_visible_at_anchor,
        _require_text,
        _stored_utc,
        _unknown_timezone,
        _verified_calendar_source_registry_id,
        _window_covers,
        and_,
        select,
    )

    code = _require_text(calendar_code, field_name="calendar_code", maximum=128)
    requested_data_kind = _require_text(data_kind, field_name="calendar data_kind", maximum=64)
    requested_frequency = _require_text(
        frequency,
        field_name="calendar frequency",
        maximum=16,
    )
    allowed_source_ids = _normalize_allowed_source_registry_ids(allowed_source_registry_ids)
    if not isinstance(window, TimeWindow):
        raise TypeError("window must be a TimeWindow")
    version = (
        _require_text(calendar_version, field_name="calendar_version", maximum=128)
        if calendar_version is not None
        else None
    )
    if knowledge_cutoff is None:
        if visibility_anchor is not None:
            raise MarketDataStoreError("VISIBILITY_ANCHOR_CUTOFF_MISMATCH")
        anchor = None
    else:
        anchor = await self._resolve_visibility_anchor(
            knowledge_cutoff=knowledge_cutoff,
            visibility_anchor=visibility_anchor,
        )

    statement = (
        select(
            MdCalendarSnapshot,
            MdPublication.published_at,
            MdPublication.visibility_sequence,
        )
        .join(
            MdPublication,
            and_(
                MdPublication.entity_type == PUBLICATION_CALENDAR_SNAPSHOT,
                MdPublication.entity_id == MdCalendarSnapshot.id,
            ),
        )
        .where(
            MdCalendarSnapshot.calendar_code == code,
            MdPublication.entity_sha256 == MdCalendarSnapshot.snapshot_sha256,
            MdPublication.published_at.is_not(None),
            MdPublication.visibility_sequence.is_not(None),
        )
    )
    if anchor is not None:
        statement = statement.where(_publication_is_visible_at_anchor(anchor))
    if version is not None:
        statement = statement.where(MdCalendarSnapshot.calendar_version == version)
    raw_rows = list((await self._db.execute(statement)).all())
    rows: list[tuple[MdCalendarSnapshot, datetime, int]] = []
    saw_unverified_source = False
    saw_unauthorized_source = False
    for row, published_at, visibility_sequence in raw_rows:
        if published_at is None or not _is_visibility_sequence(visibility_sequence):
            continue
        visible_at = _stored_utc(published_at, field_name="calendar publication")
        if anchor is not None and not anchor.permits(
            visible_at=visible_at,
            visibility_sequence=visibility_sequence,
        ):
            continue
        try:
            source_registry_id = _verified_calendar_source_registry_id(row)
        except MarketDataStoreError:
            saw_unverified_source = True
            continue
        if allowed_source_ids is not None and source_registry_id not in allowed_source_ids:
            saw_unauthorized_source = True
            continue
        rows.append((row, visible_at, visibility_sequence))

    usable: list[tuple[MdCalendarSnapshot, TimeWindow, datetime, int]] = []
    saw_integrity_error = False
    for row, published_at, visibility_sequence in rows:
        try:
            coverage_window = _calendar_coverage_window(row)
        except MarketDataStoreError:
            saw_integrity_error = True
            continue
        if coverage_window.end_at > window.start_at and coverage_window.start_at < window.end_at:
            usable.append((row, coverage_window, published_at, visibility_sequence))

    unknown_timezone = _unknown_timezone([row for row, _published_at, _sequence in rows])
    unknown_version = version or "unresolved"
    if not usable:
        if saw_unauthorized_source:
            reason = "CALENDAR_SOURCE_UNAUTHORIZED"
        elif saw_unverified_source:
            reason = "CALENDAR_SOURCE_UNVERIFIED"
        elif not rows:
            reason = "CALENDAR_VERSION_NOT_FOUND"
        elif saw_integrity_error:
            reason = "CALENDAR_INTEGRITY"
        else:
            reason = "CALENDAR_WINDOW_NOT_COVERED"
        return CalendarSnapshot.unknown(
            calendar_id=code,
            calendar_version=unknown_version,
            timezone_name=unknown_timezone,
            reason=reason,
        )
    if version is not None:
        exact = [item for item in usable if _window_covers(item[1], window)]
        if len(exact) != 1:
            return CalendarSnapshot.unknown(
                calendar_id=code,
                calendar_version=version,
                timezone_name=unknown_timezone,
                reason=(
                    "CALENDAR_AMBIGUOUS_VERSION"
                    if len(exact) > 1
                    else "CALENDAR_WINDOW_NOT_COVERED"
                ),
            )
        selected: list[tuple[MdCalendarSnapshot, TimeWindow, datetime, int]] | None = exact
    else:
        selected = _compose_calendar_segments(usable, window)
    if selected is None:
        return CalendarSnapshot.unknown(
            calendar_id=code,
            calendar_version=unknown_version,
            timezone_name=unknown_timezone,
            reason="CALENDAR_WINDOW_NOT_COVERED",
        )
    try:
        snapshots = [item[0] for item in selected]
        if len({snapshot.timezone_name for snapshot in snapshots}) != 1:
            raise MarketDataStoreError("CALENDAR_INTEGRITY")
        event_keys: list[EventKey] = []
        for snapshot, coverage_window, _published_at, _visibility_sequence in selected:
            event_keys.extend(
                await self._calendar_event_keys(
                    snapshot,
                    coverage_window,
                    requested_window=window,
                    data_kind=requested_data_kind,
                    frequency=requested_frequency,
                )
            )
        deduplicated = tuple(sorted(set(event_keys)))
        if len(deduplicated) != len(event_keys):
            raise MarketDataStoreError("CALENDAR_EVENT_INTEGRITY")
        return CalendarSnapshot(
            calendar_id=code,
            calendar_version=_composed_calendar_version(selected),
            timezone_name=snapshots[0].timezone_name,
            coverage_window=window,
            event_keys=deduplicated,
            status=CalendarStatus.KNOWN,
        )
    except MarketDataStoreError as exc:
        return CalendarSnapshot.unknown(
            calendar_id=code,
            calendar_version=_composed_calendar_version(selected),
            timezone_name=_unknown_timezone([item[0] for item in selected]),
            reason=exc.code,
        )
    except (TypeError, ValueError):
        return CalendarSnapshot.unknown(
            calendar_id=code,
            calendar_version=_composed_calendar_version(selected),
            timezone_name=_unknown_timezone([item[0] for item in selected]),
            reason="CALENDAR_EVENT_INTEGRITY",
        )


async def read_calendar_for_context(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    *,
    calendar_version: str | None = None,
    knowledge_cutoff: datetime | None = None,
    visibility_anchor: MarketDataVisibilityAnchor | None = None,
    allowed_source_registry_ids: frozenset[str] | None = None,
) -> CalendarSnapshot:
    """Load calendar evidence for a resolved query's exact market and window."""
    from app.services.market_data.store import (
        TimeWindow,
        _assert_context_integrity,
    )

    _assert_context_integrity(context)
    return await self.read_calendar(
        calendar_code=context.coverage_identity.market,
        window=TimeWindow(start_at=context.query.start, end_at=context.query.end),
        calendar_version=calendar_version,
        knowledge_cutoff=knowledge_cutoff,
        visibility_anchor=visibility_anchor,
        data_kind=context.query.data_kind,
        frequency=context.query.frequency or "snapshot",
        allowed_source_registry_ids=allowed_source_registry_ids,
    )


async def read_calendar_trading_day_events_for_context(
    self: MarketDataStore,
    context: ResolvedMarketDataQueryContext,
    *,
    knowledge_cutoff: datetime,
    visibility_anchor: MarketDataVisibilityAnchor | None = None,
    allowed_source_registry_ids: frozenset[str] | None = None,
) -> CalendarTradingDayEvents:
    """Return a one-to-one daily source-date map from one governed snapshot.

    This is deliberately narrower than :meth:`read_calendar_for_context`.
    It is for controlled legacy imports that must preserve the source table's
    ``DATE`` label while using the exact published EventKey.  It reuses the
    regular calendar read first, then requires that its proof comes from one
    visible snapshot; composed rolling segments remain unavailable here
    because no importer may erase their snapshot boundary.
    """
    from app.services.market_data.store import (
        CalendarStatus,
        CalendarTradingDayEvents,
        MarketDataStoreError,
        TimeWindow,
        _assert_context_integrity,
        _unknown_calendar_trading_day_events,
    )

    _assert_context_integrity(context)
    anchor = await self._resolve_visibility_anchor(
        knowledge_cutoff=knowledge_cutoff,
        visibility_anchor=visibility_anchor,
    )
    code = context.coverage_identity.market
    window = TimeWindow(start_at=context.query.start, end_at=context.query.end)
    calendar = await self.read_calendar_for_context(
        context,
        knowledge_cutoff=knowledge_cutoff,
        visibility_anchor=anchor,
        allowed_source_registry_ids=allowed_source_registry_ids,
    )
    if calendar.status is not CalendarStatus.KNOWN:
        return _unknown_calendar_trading_day_events(
            calendar=calendar,
            visibility_anchor=anchor,
            data_kind=context.query.data_kind,
            frequency=context.query.frequency or "snapshot",
            reason=calendar.reason or "CALENDAR_INTEGRITY",
        )
    if calendar.calendar_version.startswith("composed:"):
        return _unknown_calendar_trading_day_events(
            calendar=calendar,
            visibility_anchor=anchor,
            data_kind=context.query.data_kind,
            frequency=context.query.frequency or "snapshot",
            reason="CALENDAR_TRADING_DAY_SNAPSHOT_AMBIGUOUS",
        )

    snapshot, source_reason = await self._read_visible_calendar_snapshot_for_trading_days(
        calendar_code=code,
        calendar_version=calendar.calendar_version,
        visibility_anchor=anchor,
        allowed_source_registry_ids=allowed_source_registry_ids,
    )
    if snapshot is None:
        return _unknown_calendar_trading_day_events(
            calendar=calendar,
            visibility_anchor=anchor,
            data_kind=context.query.data_kind,
            frequency=context.query.frequency or "snapshot",
            reason=source_reason or "CALENDAR_VERSION_NOT_FOUND",
        )
    try:
        events = await self._read_calendar_trading_day_events(
            snapshot=snapshot,
            window=window,
            data_kind=context.query.data_kind,
            frequency=context.query.frequency or "snapshot",
            expected_event_keys=calendar.event_keys,
        )
    except MarketDataStoreError as exc:
        return _unknown_calendar_trading_day_events(
            calendar=calendar,
            visibility_anchor=anchor,
            data_kind=context.query.data_kind,
            frequency=context.query.frequency or "snapshot",
            reason=exc.code,
        )
    return CalendarTradingDayEvents(
        calendar_code=calendar.calendar_id,
        calendar_version=calendar.calendar_version,
        data_kind=context.query.data_kind,
        frequency=context.query.frequency or "snapshot",
        calendar_snapshot_id=snapshot.id,
        timezone_name=calendar.timezone_name,
        coverage_window=calendar.coverage_window,
        visibility_anchor=anchor,
        status=CalendarStatus.KNOWN,
        reason=None,
        events=events,
    )


async def _read_visible_calendar_snapshot_for_trading_days(
    self: MarketDataStore,
    *,
    calendar_code: str,
    calendar_version: str,
    visibility_anchor: MarketDataVisibilityAnchor,
    allowed_source_registry_ids: frozenset[str] | None,
) -> tuple[MdCalendarSnapshot | None, str | None]:
    """Revalidate the single snapshot boundary retained by a known calendar."""
    from app.services.market_data.store import (
        PUBLICATION_CALENDAR_SNAPSHOT,
        MarketDataStoreError,
        MdCalendarSnapshot,
        MdPublication,
        _is_visibility_sequence,
        _normalize_allowed_source_registry_ids,
        _publication_is_visible_at_anchor,
        _stored_utc,
        _verified_calendar_source_registry_id,
        and_,
        select,
    )

    allowed_source_ids = _normalize_allowed_source_registry_ids(allowed_source_registry_ids)
    rows = list(
        (
            await self._db.execute(
                select(
                    MdCalendarSnapshot,
                    MdPublication.published_at,
                    MdPublication.visibility_sequence,
                )
                .join(
                    MdPublication,
                    and_(
                        MdPublication.entity_type == PUBLICATION_CALENDAR_SNAPSHOT,
                        MdPublication.entity_id == MdCalendarSnapshot.id,
                    ),
                )
                .where(
                    MdCalendarSnapshot.calendar_code == calendar_code,
                    MdCalendarSnapshot.calendar_version == calendar_version,
                    MdPublication.entity_sha256 == MdCalendarSnapshot.snapshot_sha256,
                    MdPublication.published_at.is_not(None),
                    MdPublication.visibility_sequence.is_not(None),
                    _publication_is_visible_at_anchor(visibility_anchor),
                )
            )
        ).all()
    )
    saw_unverified = False
    saw_unauthorized = False
    verified: list[MdCalendarSnapshot] = []
    for snapshot, published_at, visibility_sequence in rows:
        if published_at is None or not _is_visibility_sequence(visibility_sequence):
            continue
        visible_at = _stored_utc(published_at, field_name="calendar publication")
        if not visibility_anchor.permits(
            visible_at=visible_at,
            visibility_sequence=visibility_sequence,
        ):
            continue
        try:
            source_registry_id = _verified_calendar_source_registry_id(snapshot)
        except MarketDataStoreError:
            saw_unverified = True
            continue
        if allowed_source_ids is not None and source_registry_id not in allowed_source_ids:
            saw_unauthorized = True
            continue
        verified.append(snapshot)
    if len(verified) == 1:
        return verified[0], None
    if saw_unauthorized:
        return None, "CALENDAR_SOURCE_UNAUTHORIZED"
    if saw_unverified:
        return None, "CALENDAR_SOURCE_UNVERIFIED"
    if len(verified) > 1:
        return None, "CALENDAR_TRADING_DAY_SNAPSHOT_AMBIGUOUS"
    return None, "CALENDAR_VERSION_NOT_FOUND"


async def _read_calendar_trading_day_events(
    self: MarketDataStore,
    *,
    snapshot: MdCalendarSnapshot,
    window: TimeWindow,
    data_kind: str,
    frequency: str,
    expected_event_keys: Sequence[EventKey],
) -> tuple[CalendarTradingDayEvent, ...]:
    """Bind each selected daily EventKey to exactly one persisted date label."""
    from app.services.market_data.store import (
        CalendarTradingDayEvent,
        EventKey,
        MarketDataStoreError,
        MdCalendarEvent,
        _stored_utc,
        calendar_coverage_descriptor,
        calendar_coverage_event_key,
        date,
        select,
    )

    expected = tuple(expected_event_keys)
    if len(set(expected)) != len(expected):
        raise MarketDataStoreError("CALENDAR_TRADING_DAY_EVENT_INTEGRITY")
    expected_set = frozenset(expected)
    rows = list(
        (
            await self._db.execute(
                select(MdCalendarEvent)
                .where(
                    MdCalendarEvent.calendar_snapshot_id == snapshot.id,
                    MdCalendarEvent.event_start.is_not(None),
                    MdCalendarEvent.event_start >= window.start_at,
                    MdCalendarEvent.event_start < window.end_at,
                )
                .order_by(
                    MdCalendarEvent.trading_date,
                    MdCalendarEvent.event_start,
                    MdCalendarEvent.id,
                )
            )
        )
        .scalars()
        .all()
    )
    mapped: list[CalendarTradingDayEvent] = []
    for row in rows:
        if not row.is_trading_day or row.event_type != "session":
            continue
        try:
            descriptor = calendar_coverage_descriptor(row.event_payload_json)
        except ValueError as exc:
            raise MarketDataStoreError("CALENDAR_TRADING_DAY_EVENT_INTEGRITY") from exc
        if descriptor != (data_kind, frequency):
            continue
        if row.event_start is None or not isinstance(row.trading_date, date):
            raise MarketDataStoreError("CALENDAR_TRADING_DAY_EVENT_INTEGRITY")
        event_key = EventKey(_stored_utc(row.event_start, field_name="calendar event_start"))
        try:
            expected_coverage_key = calendar_coverage_event_key(
                event_start=event_key.event_at,
                data_kind=data_kind,
                frequency=frequency,
            )
        except ValueError as exc:
            raise MarketDataStoreError("CALENDAR_TRADING_DAY_EVENT_INTEGRITY") from exc
        if row.coverage_event_key != expected_coverage_key or event_key not in expected_set:
            raise MarketDataStoreError("CALENDAR_TRADING_DAY_EVENT_INTEGRITY")
        mapped.append(
            CalendarTradingDayEvent(
                trading_date=row.trading_date,
                event_key=event_key,
            )
        )
    try:
        result = tuple(mapped)
        by_date = {item.trading_date: item.event_key for item in result}
        if len(by_date) != len(result):
            raise ValueError("duplicate trading date")
        if frozenset(by_date.values()) != expected_set:
            raise ValueError("expected EventKey set mismatch")
        return tuple(
            CalendarTradingDayEvent(trading_date=trading_date, event_key=by_date[trading_date])
            for trading_date in sorted(by_date)
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataStoreError("CALENDAR_TRADING_DAY_EVENT_INTEGRITY") from exc


def _calendar_coverage_window(snapshot: MdCalendarSnapshot) -> TimeWindow:
    """Read explicit calendar coverage metadata without deriving a weekday rule."""
    from app.services.market_data.store import (
        Mapping,
        MarketDataStoreError,
        TimeWindow,
        _json_safe_mapping,
        _parse_timestamp,
    )

    definition = _json_safe_mapping(snapshot.definition_json, field_name="calendar definition")
    raw_window = definition.get("coverage_window")
    if raw_window is not None:
        if not isinstance(raw_window, Mapping):
            raise MarketDataStoreError("CALENDAR_INTEGRITY")
        start_value = raw_window.get("start_at")
        end_value = raw_window.get("end_at")
    else:
        start_value = definition.get("coverage_start_at")
        end_value = definition.get("coverage_end_at")
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        raise MarketDataStoreError("CALENDAR_INTEGRITY")
    try:
        return TimeWindow(
            start_at=_parse_timestamp(start_value, field_name="calendar coverage_start_at"),
            end_at=_parse_timestamp(end_value, field_name="calendar coverage_end_at"),
        )
    except (TypeError, ValueError) as exc:
        raise MarketDataStoreError("CALENDAR_INTEGRITY") from exc


def _verified_calendar_source_registry_id(snapshot: MdCalendarSnapshot) -> str:
    """Validate immutable calendar governance before it can prove coverage.

    Calendar imports freeze a registry-backed descriptor into the immutable
    definition.  The reader recomputes its digest and binds it to the relational
    source columns before treating an importer-written snapshot as evidence.
    This verifies persisted structure and integrity; it is not a signature over
    arbitrary in-process input.  The current v2 access grant performs the
    separate present-tense source entitlement check through
    ``allowed_source_registry_ids``.
    """
    from app.services.market_data.store import (
        _CALENDAR_SOURCE_GOVERNANCE_VERSION,
        CALENDAR_SOURCE_GOVERNANCE_STATE_VERIFIED,
        MarketDataStoreError,
        _canonical_json,
        _json_safe_mapping,
        _require_authorization_upper,
        _require_calendar_governance_tokens,
        _require_optional_utc_authorization_timestamp,
        _require_sha256_digest,
        _require_text,
        _require_utc_authorization_timestamp,
        _sha256,
    )

    if snapshot.source_governance_state != CALENDAR_SOURCE_GOVERNANCE_STATE_VERIFIED:
        raise MarketDataStoreError("CALENDAR_SOURCE_UNVERIFIED")
    source_registry_id = _require_text(
        snapshot.source_registry_id,
        field_name="calendar source_registry_id",
        maximum=128,
    )
    descriptor_sha256 = _require_sha256_digest(
        snapshot.source_governance_descriptor_sha256,
        code="CALENDAR_SOURCE_GOVERNANCE_INTEGRITY",
    )
    definition = _json_safe_mapping(snapshot.definition_json, field_name="calendar definition")
    manifest_hash = _require_sha256_digest(
        definition.get("manifest_hash"),
        code="CALENDAR_SOURCE_GOVERNANCE_INTEGRITY",
    )
    snapshot_hash = _require_sha256_digest(
        snapshot.snapshot_sha256,
        code="CALENDAR_SOURCE_GOVERNANCE_INTEGRITY",
    )
    if manifest_hash != snapshot_hash:
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    governance = _json_safe_mapping(
        definition.get("source_governance"),
        field_name="calendar source governance",
    )
    actual_descriptor = governance.pop("descriptor_hash", None)
    if actual_descriptor != descriptor_sha256:
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    if _sha256(_canonical_json(governance, field_name="calendar source governance")) != (
        descriptor_sha256
    ):
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    if set(governance) != {
        "version",
        "source_registry_id",
        "registry_updated_at",
        "license_status",
        "asset_types",
        "jurisdictions",
        "allowed_uses",
        "effective_from",
        "effective_to",
        "retention_policy",
        "retention_expires_at",
        "redistribution_policy",
        "approval_reference",
        "evidence_uri",
        "evidence_content_hash",
        "calendar_manifest_hash",
        "decision",
    }:
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    if (
        governance["version"] != _CALENDAR_SOURCE_GOVERNANCE_VERSION
        or governance["source_registry_id"] != source_registry_id
        or governance["calendar_manifest_hash"] != manifest_hash
        or governance["decision"] != "ALLOW"
    ):
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    _require_utc_authorization_timestamp(
        governance["registry_updated_at"],
        field_name="calendar source registry_updated_at",
    )
    _require_authorization_upper(
        governance["license_status"],
        field_name="calendar source license_status",
        maximum=64,
    )
    _require_calendar_governance_tokens(
        governance["asset_types"],
        field_name="calendar source asset_types",
    )
    _require_calendar_governance_tokens(
        governance["jurisdictions"],
        field_name="calendar source jurisdictions",
    )
    _require_calendar_governance_tokens(
        governance["allowed_uses"],
        field_name="calendar source allowed_uses",
    )
    _require_utc_authorization_timestamp(
        governance["effective_from"],
        field_name="calendar source effective_from",
    )
    _require_optional_utc_authorization_timestamp(
        governance["effective_to"],
        field_name="calendar source effective_to",
    )
    _require_authorization_upper(
        governance["retention_policy"],
        field_name="calendar source retention_policy",
        maximum=64,
    )
    _require_optional_utc_authorization_timestamp(
        governance["retention_expires_at"],
        field_name="calendar source retention_expires_at",
    )
    _require_authorization_upper(
        governance["redistribution_policy"],
        field_name="calendar source redistribution_policy",
        maximum=64,
    )
    _require_text(
        governance["approval_reference"],
        field_name="calendar approval_reference",
        maximum=255,
    )
    _require_text(
        governance["evidence_uri"],
        field_name="calendar evidence_uri",
        maximum=2048,
    )
    _require_sha256_digest(
        governance["evidence_content_hash"],
        code="CALENDAR_SOURCE_GOVERNANCE_INTEGRITY",
    )
    return source_registry_id


def _require_calendar_governance_tokens(value: object, *, field_name: str) -> tuple[str, ...]:
    """Require a canonical list frozen by the registry-backed importer."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        _require_authorization_upper,
    )

    if not isinstance(value, list):
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    normalized = tuple(
        _require_authorization_upper(item, field_name=field_name, maximum=128) for item in value
    )
    if not normalized or normalized != tuple(sorted(set(normalized))):
        raise MarketDataStoreError("CALENDAR_SOURCE_GOVERNANCE_INTEGRITY")
    return normalized


def _window_covers(coverage_window: TimeWindow, requested_window: TimeWindow) -> bool:
    """Return whether explicitly advertised calendar evidence covers a request."""
    return (
        coverage_window.start_at <= requested_window.start_at
        and requested_window.end_at <= coverage_window.end_at
    )


def _window_intersection(left: TimeWindow, right: TimeWindow) -> TimeWindow:
    """Return a non-empty half-open overlap without widening either evidence window."""
    from app.services.market_data.store import (
        MarketDataStoreError,
        TimeWindow,
    )

    start_at = max(left.start_at, right.start_at)
    end_at = min(left.end_at, right.end_at)
    if end_at <= start_at:
        raise MarketDataStoreError("CALENDAR_WINDOW_NOT_COVERED")
    return TimeWindow(start_at=start_at, end_at=end_at)


def _compose_calendar_segments(
    candidates: Sequence[tuple[MdCalendarSnapshot, TimeWindow, datetime, int]],
    requested: TimeWindow,
) -> list[tuple[MdCalendarSnapshot, TimeWindow, datetime, int]] | None:
    """Select contiguous immutable blocks that prove one full calendar window.

    Import serialization rejects overlaps. This reader repeats that invariant
    defensively and concatenates adjacent rolling manifests without inventing
    weekday or holiday behavior. A gap remains an unknown calendar.
    """

    selected: list[tuple[MdCalendarSnapshot, TimeWindow, datetime, int]] = []
    cursor = requested.start_at
    ordered = sorted(candidates, key=lambda item: (item[1].start_at, item[1].end_at, item[0].id))
    for candidate in ordered:
        _snapshot, coverage, _published_at, _visibility_sequence = candidate
        if coverage.end_at <= cursor:
            continue
        if coverage.start_at > cursor:
            break
        if selected and coverage.start_at < cursor:
            return None
        selected.append(candidate)
        cursor = coverage.end_at
        if cursor >= requested.end_at:
            return selected
    return None


def _composed_calendar_version(
    segments: Sequence[tuple[MdCalendarSnapshot, TimeWindow, datetime, int]],
) -> str:
    """Return a bounded audit label for one or more immutable calendar blocks."""
    from app.services.market_data.store import (
        hashlib,
    )

    versions = tuple(item[0].calendar_version for item in segments)
    if len(versions) == 1:
        return versions[0]
    digest = hashlib.sha256("|".join(versions).encode("utf-8")).hexdigest()[:24]
    return f"composed:{digest}"


def _unknown_timezone(rows: Sequence[MdCalendarSnapshot]) -> str:
    """Select a valid declared timezone when possible, otherwise use UTC for unknown DTOs."""
    from app.services.market_data.store import (
        CalendarSnapshot,
    )

    for row in rows:
        try:
            CalendarSnapshot.unknown(
                calendar_id="unknown",
                calendar_version="unknown",
                timezone_name=row.timezone_name,
                reason="unknown",
            )
        except (TypeError, ValueError):
            continue
        return row.timezone_name
    return "UTC"


def _unknown_calendar_trading_day_events(
    *,
    calendar: CalendarSnapshot,
    visibility_anchor: MarketDataVisibilityAnchor,
    data_kind: str,
    frequency: str,
    reason: str,
) -> CalendarTradingDayEvents:
    """Return a typed absence without leaking a partial date-to-key map."""
    from app.services.market_data.store import (
        CalendarStatus,
        CalendarTradingDayEvents,
        _require_text,
    )

    return CalendarTradingDayEvents(
        calendar_code=calendar.calendar_id,
        calendar_version=calendar.calendar_version,
        data_kind=data_kind,
        frequency=frequency,
        calendar_snapshot_id=None,
        timezone_name=calendar.timezone_name,
        coverage_window=None,
        visibility_anchor=visibility_anchor,
        status=CalendarStatus.UNKNOWN,
        reason=_require_text(reason, field_name="calendar trading-day reason", maximum=128),
        events=(),
    )


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    """Parse an explicit JSON timestamp while requiring an offset."""
    from app.services.market_data.store import (
        _require_aware_utc,
        datetime,
    )

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601") from exc
    return _require_aware_utc(parsed, field_name=field_name)


def _require_aware_utc(value: datetime, *, field_name: str) -> datetime:
    """Validate a public/provider timestamp instead of assuming its timezone."""
    from app.services.market_data.store import (
        UTC,
        MarketDataStoreError,
        datetime,
    )

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataStoreError("TIMESTAMP_INVALID")
    return value.astimezone(UTC)


def _stored_utc(value: datetime, *, field_name: str) -> datetime:
    """Read a timestamp stored by this service, treating SQLite naive values as UTC."""
    from app.services.market_data.store import (
        UTC,
        MarketDataStoreError,
        datetime,
    )

    if not isinstance(value, datetime):
        raise MarketDataStoreError("LOCAL_OBSERVATION_INTEGRITY")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
