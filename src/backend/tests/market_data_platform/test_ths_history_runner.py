"""THS history runner's typed reference contracts and failure summaries."""

from __future__ import annotations

from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.market_data import calendar_importer as calendar_importer_module
from app.services.market_data import ths_history_runner as ths_history_runner_module
from app.services.market_data import ths_reference_collector as ths_reference_collector_module
from app.services.market_data.access import MarketDataSourceAuthorization
from app.services.market_data.catalog import DatasetStorageResolution
from app.services.market_data.providers import MarketDataProviderRequest
from app.services.market_data.query_resolution import ResolvedMarketDataQueryContext
from app.services.market_data.ths_dump_importer import (
    THS_ADJUSTMENT_FACTORS_DATASET_CODE,
    THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS,
    THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
    THS_DAILY_K_DATASET_CODE,
    THS_DUMP_PROVIDER_ID,
)
from app.services.market_data.ths_envelope import parse_ths_envelope
from app.services.market_data.ths_history_runner import (
    ThsHistoryError,
    ThsHistoryRunner,
    _canonical_ths_calendar_response_hash,
)
from app.services.market_data.ths_reference import normalize_calendar
from app.services.market_data.ths_reference_collector import THS_FINANCIALS_STATEMENTS
from scripts import backfill_ths_history, collect_ths_daily


def test_reference_context_and_request_returns_concrete_contracts() -> None:
    runner = object.__new__(ThsHistoryRunner)
    storage = DatasetStorageResolution(
        dataset_id="dataset-ths-reference",
        dataset_code=THS_ADJUSTMENT_FACTORS_DATASET_CODE,
        storage_id="market-data",
        engine="sqlite",
        database_name="local",
        physical_table="md_observation_revisions",
        write_mode="canonical_read_write",
    )

    context, request = runner._reference_context_and_request(
        dataset_code=THS_ADJUSTMENT_FACTORS_DATASET_CODE,
        canonical_id="instrument:stock:CN-SSE:600519",
        display_symbol="600519.SH",
        venue="CN-SSE",
        required_fields=THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS,
        source_policy_id=THS_ADJUSTMENT_FACTORS_SOURCE_POLICY_ID,
        storage=storage,
    )

    assert isinstance(context, ResolvedMarketDataQueryContext)
    assert isinstance(request, MarketDataProviderRequest)
    assert request.canonical_id == "instrument:stock:CN-SSE:600519"
    assert request.required_fields == THS_ADJUSTMENT_FACTORS_REQUIRED_FIELDS


@pytest.mark.asyncio
async def test_adjustment_factor_failures_keep_string_samples_and_report_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(ThsHistoryRunner)
    session = _FakeSession()
    runner._session = session
    runner._catalog = SimpleNamespace(
        resolve_primary=AsyncMock(return_value=_storage(THS_ADJUSTMENT_FACTORS_DATASET_CODE))
    )
    runner._store = SimpleNamespace(ensure_source_authorization_before_provider_io=AsyncMock())
    runner._downloader = SimpleNamespace(
        fetch_ths_json=Mock(side_effect=RuntimeError("fixture failure"))
    )
    runner.ensure_control_plane = AsyncMock(return_value=object())
    runner._venue_authorizations = Mock(return_value={"CN-SSE": _authorization("CN-SSE")})
    monkeypatch.setattr(
        ths_reference_collector_module,
        "ThsReferenceCollector",
        Mock(return_value=SimpleNamespace(persist_adjustment_factors=AsyncMock())),
    )

    report = await runner.backfill_adjustment_factors(
        symbols=["600519.SH"],
        commit_every=None,
    )

    assert report == {
        "target_count": 1,
        "persisted_symbol_count": 0,
        "skipped_count": 0,
        "failed_count": 1,
        "failed_samples": ["600519.SH:RuntimeError"],
    }
    assert isinstance(report["failed_samples"][0], str)
    assert len(session.savepoints) == 1
    session.savepoints[0].rollback.assert_awaited_once()
    session.rollback.assert_not_awaited()


class _FakeSavepoint:
    def __init__(self) -> None:
        self.rollback = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self) -> _FakeSavepoint:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()
        return False


class _FakeSession:
    def __init__(self, *, active: bool = False) -> None:
        self.active = active
        self.begin = AsyncMock(side_effect=self._begin)
        self.savepoints: list[_FakeSavepoint] = []
        self.begin_nested = Mock(side_effect=self._begin_nested)
        self.get_bind = Mock(
            return_value=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        )
        self.commit = AsyncMock(side_effect=self._finish)
        self.rollback = AsyncMock(side_effect=self._finish)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def in_transaction(self) -> bool:
        return self.active

    async def _begin(self) -> None:
        self.active = True

    def _begin_nested(self) -> _FakeSavepoint:
        self.active = True
        savepoint = _FakeSavepoint()
        self.savepoints.append(savepoint)
        return savepoint

    async def _finish(self) -> None:
        self.active = False


def _calendar_payload(
    *,
    request_id: str,
    date_ms: int = 1716105600000,
    date: str = "20240520",
    timestamp_ms: int | None = None,
) -> dict[str, object]:
    data: dict[str, object] = {
        "item": [{"date_ms": date_ms, "date": date}],
    }
    if timestamp_ms is not None:
        data["timestamp"] = timestamp_ms
    return {
        "code": 0,
        "message": "success",
        "request_id": request_id,
        "data": data,
    }


def _storage(dataset_code: str) -> DatasetStorageResolution:
    return DatasetStorageResolution(
        dataset_id=f"dataset-{dataset_code}",
        dataset_code=dataset_code,
        storage_id="market-data",
        engine="sqlite",
        database_name="local",
        physical_table="md_observation_revisions",
        write_mode="canonical_read_write",
    )


def _authorization(venue: str) -> MarketDataSourceAuthorization:
    return MarketDataSourceAuthorization(
        source_registry_id=THS_DUMP_PROVIDER_ID,
        registry_updated_at="2026-01-01T00:00:00+00:00",
        asset_type="stock",
        market=venue,
        purpose="display",
        license_status="APPROVED",
        allowed_uses=("DISPLAY",),
        jurisdictions=("CN",),
        effective_from="2020-01-01T00:00:00+00:00",
        effective_to=None,
        retention_policy="MARKET-DATA-PLATFORM-V1",
        retention_expires_at=None,
        redistribution_policy="NO_REDISTRIBUTION",
        principal_scope="principal-v1:ths-history-runner",
        tenant_scope="default",
        entitlement_revision="a" * 64,
        decision="ALLOW",
        descriptor_hash="b" * 64,
    )


def _calendar_runner(
    session: AsyncSession | _FakeSession, payloads: list[dict[str, object]]
) -> ThsHistoryRunner:
    runner = object.__new__(ThsHistoryRunner)
    runner._session = session
    runner._catalog = SimpleNamespace(
        resolve_primary=AsyncMock(return_value=_storage(THS_DAILY_K_DATASET_CODE))
    )
    runner._store = SimpleNamespace(ensure_source_authorization_before_provider_io=AsyncMock())
    runner._downloader = SimpleNamespace(
        _base_url="https://fuyao.aicubes.cn",
        fetch_ths_json=Mock(side_effect=payloads),
    )
    runner.ensure_control_plane = AsyncMock(return_value=object())
    runner._venue_authorizations = Mock(return_value={"CN-SSE": _authorization("CN-SSE")})
    return runner


def _patch_calendar_importer(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    importer = SimpleNamespace(
        import_payload=AsyncMock(return_value=SimpleNamespace(event_count=1)),
        publish_staged=AsyncMock(),
    )
    monkeypatch.setattr(
        calendar_importer_module,
        "MarketDataCalendarImporter",
        Mock(return_value=importer),
    )
    return importer


def _calendar_response_hash(payload: dict[str, object]) -> str:
    return _canonical_ths_calendar_response_hash(normalize_calendar(parse_ths_envelope(payload)))


@pytest.mark.asyncio
async def test_sync_calendar_defaults_to_rollback_dry_run_with_canonical_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_response = _calendar_payload(request_id="calendar-1")
    transport_changed_response = _calendar_payload(request_id="calendar-2")
    transport_changed_response["message"] = "another transport message"
    session = _FakeSession()
    runner = _calendar_runner(session, [first_response, transport_changed_response])
    importer = _patch_calendar_importer(monkeypatch)
    events: list[str] = []

    async def preflight(*args: object, **kwargs: object) -> None:
        events.append("authorization")

    def download(path: str) -> dict[str, object]:
        events.append("download")
        return first_response if events.count("download") == 1 else transport_changed_response

    runner._store.ensure_source_authorization_before_provider_io.side_effect = preflight
    runner._downloader.fetch_ths_json.side_effect = download

    assert await runner.sync_calendar() == 1
    assert await runner.sync_calendar() == 1

    calls = importer.import_payload.await_args_list
    assert [call.kwargs["dry_run"] for call in calls] == [True, True]
    manifests = [call.kwargs["payload"] for call in calls]
    assert [manifest["evidence_content_hash"] for manifest in manifests] == [
        _calendar_response_hash(first_response),
        _calendar_response_hash(transport_changed_response),
    ]
    assert manifests[0]["evidence_content_hash"] == manifests[1]["evidence_content_hash"]
    assert manifests[0] == manifests[1]
    assert all(manifest["evidence_content_hash"] != "0" * 64 for manifest in manifests)
    assert all(
        manifest["evidence_uri"] == "https://fuyao.aicubes.cn/api/a-share/calendar/trading-days"
        for manifest in manifests
    )
    runner.ensure_control_plane.assert_awaited()
    assert events == ["authorization", "download", "authorization", "download"]
    assert runner._store.ensure_source_authorization_before_provider_io.await_count == 2
    session.commit.assert_not_awaited()
    assert session.rollback.await_count == 2
    importer.publish_staged.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_calendar_dry_run_rolls_back_only_its_outer_transaction_savepoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE calendar_dry_run (id INTEGER PRIMARY KEY)"))

    root_transaction_events: list[str] = []

    def record_root_commit(connection: object) -> None:
        root_transaction_events.append("commit")

    def record_root_rollback(connection: object) -> None:
        root_transaction_events.append("rollback")

    event.listen(engine.sync_engine, "commit", record_root_commit)
    event.listen(engine.sync_engine, "rollback", record_root_rollback)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            await session.begin()
            runner = _calendar_runner(session, [_calendar_payload(request_id="outer-tx-dry-run")])
            importer = SimpleNamespace(
                import_payload=AsyncMock(),
                publish_staged=AsyncMock(),
            )

            async def import_with_dry_run_write(
                *, payload: dict[str, object], dry_run: bool
            ) -> SimpleNamespace:
                assert dry_run is True
                await session.execute(text("INSERT INTO calendar_dry_run (id) VALUES (1)"))
                return SimpleNamespace(event_count=1)

            importer.import_payload.side_effect = import_with_dry_run_write
            monkeypatch.setattr(
                calendar_importer_module,
                "MarketDataCalendarImporter",
                Mock(return_value=importer),
            )

            assert await runner.sync_calendar() == 1

            assert session.in_transaction()
            row_count = await session.scalar(text("SELECT COUNT(*) FROM calendar_dry_run"))
            assert row_count == 0
            assert root_transaction_events == []
            importer.import_payload.assert_awaited_once()
            assert importer.import_payload.await_args.kwargs["dry_run"] is True

            await session.execute(text("INSERT INTO calendar_dry_run (id) VALUES (2)"))
            await session.commit()
            assert root_transaction_events == ["commit"]
    finally:
        event.remove(engine.sync_engine, "commit", record_root_commit)
        event.remove(engine.sync_engine, "rollback", record_root_rollback)
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_calendar_repeated_same_day_apply_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_response = _calendar_payload(request_id="calendar-apply-1", timestamp_ms=1716100000000)
    second_response = _calendar_payload(request_id="calendar-apply-2", timestamp_ms=1716200000000)
    session = _FakeSession()
    runner = _calendar_runner(session, [first_response, second_response])
    importer = _patch_calendar_importer(monkeypatch)
    as_of = datetime(2026, 9, 21, tzinfo=timezone.utc)

    assert await runner.sync_calendar(apply=True, as_of=as_of) == 1
    assert await runner.sync_calendar(apply=True, as_of=as_of) == 1

    runner.ensure_control_plane.assert_awaited()
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()
    assert importer.import_payload.await_count == 2
    calls = importer.import_payload.await_args_list
    assert all(call.kwargs["dry_run"] is False for call in calls)
    manifests = [call.kwargs["payload"] for call in calls]
    assert manifests[0] == manifests[1]
    assert manifests[0]["calendar_version"] == "ths-2026-09-21"
    assert manifests[0]["evidence_content_hash"] == _calendar_response_hash(first_response)
    assert manifests[0]["evidence_uri"] == (
        "https://fuyao.aicubes.cn/api/a-share/calendar/trading-days"
    )
    assert runner._store.ensure_source_authorization_before_provider_io.await_count == 2
    importer.publish_staged.assert_not_awaited()


def test_calendar_evidence_hash_tracks_business_rows_not_transport_metadata() -> None:
    first_response = _calendar_payload(request_id="request-1", timestamp_ms=1716100000000)
    same_business_data = _calendar_payload(request_id="request-2", timestamp_ms=1716200000000)
    changed_business_data = _calendar_payload(
        request_id="request-3",
        date_ms=1716192000000,
        date="20240521",
        timestamp_ms=1716200000000,
    )

    assert _calendar_response_hash(first_response) == _calendar_response_hash(same_business_data)
    assert _calendar_response_hash(first_response) != _calendar_response_hash(changed_business_data)


@pytest.mark.parametrize(
    "calendar_rows",
    [[], [{"date_ms": object(), "date": "20240520"}]],
)
def test_calendar_evidence_hash_fails_closed_for_empty_or_non_json_payload(
    calendar_rows: object,
) -> None:
    with pytest.raises(ThsHistoryError, match="THS_CALENDAR_EVIDENCE_INVALID"):
        _canonical_ths_calendar_response_hash(calendar_rows)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "dataset_code"),
    [
        ("adjustment", THS_ADJUSTMENT_FACTORS_DATASET_CODE),
        ("financial", THS_FINANCIALS_STATEMENTS["income"]),
    ],
)
async def test_reference_backfills_recheck_authorization_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    dataset_code: str,
) -> None:
    runner = object.__new__(ThsHistoryRunner)
    fetch = Mock(return_value={"code": 0, "data": {"item": []}})
    runner._session = _FakeSession()
    runner._catalog = SimpleNamespace(
        resolve_primary=AsyncMock(return_value=_storage(dataset_code))
    )
    runner._store = SimpleNamespace(
        ensure_source_authorization_before_provider_io=AsyncMock(
            side_effect=RuntimeError("source grant revoked")
        )
    )
    runner._downloader = SimpleNamespace(fetch_ths_json=fetch)
    runner.ensure_control_plane = AsyncMock(return_value=object())
    runner._venue_authorizations = Mock(return_value={"CN-SSE": _authorization("CN-SSE")})
    collector = SimpleNamespace(
        persist_adjustment_factors=AsyncMock(),
        persist_financials=AsyncMock(),
    )
    monkeypatch.setattr(
        ths_reference_collector_module,
        "ThsReferenceCollector",
        Mock(return_value=collector),
    )

    if operation == "adjustment":
        report = await runner.backfill_adjustment_factors(
            symbols=["600519.SH"],
            commit_every=None,
        )
    else:
        report = await runner.backfill_financials(
            statement="income",
            symbols=["600519.SH"],
            commit_every=None,
        )

    assert report["failed_samples"] == ["600519.SH:RuntimeError"]
    assert report["failed_count"] == 1
    runner._store.ensure_source_authorization_before_provider_io.assert_awaited_once()
    context, authorization = (
        runner._store.ensure_source_authorization_before_provider_io.await_args.args
    )
    assert context.identity.venue == "CN-SSE"
    assert context.query.dataset_code == dataset_code
    assert authorization.market == "CN-SSE"
    assert (
        runner._store.ensure_source_authorization_before_provider_io.await_args.kwargs[
            "provider_id"
        ]
        == THS_DUMP_PROVIDER_ID
    )
    fetch.assert_not_called()
    assert len(runner._session.savepoints) == 1
    runner._session.savepoints[0].rollback.assert_awaited_once_with()
    runner._session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_calendar_authorization_rejection_skips_fetch_and_rolls_back_apply() -> None:
    runner = _calendar_runner(_FakeSession(), [_calendar_payload(request_id="never-fetched")])
    session = runner._session

    async def begin_control_plane() -> object:
        session.active = True
        return object()

    runner.ensure_control_plane = AsyncMock(side_effect=begin_control_plane)
    runner._store.ensure_source_authorization_before_provider_io.side_effect = RuntimeError(
        "source grant revoked"
    )

    with pytest.raises(RuntimeError, match="source grant revoked"):
        await runner.sync_calendar(apply=True)

    runner._store.ensure_source_authorization_before_provider_io.assert_awaited_once()
    context, authorization = (
        runner._store.ensure_source_authorization_before_provider_io.await_args.args
    )
    assert context.identity.venue == "CN-SSE"
    assert context.query.dataset_code == THS_DAILY_K_DATASET_CODE
    assert authorization.market == "CN-SSE"
    runner._downloader.fetch_ths_json.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_sync_calendar_apply_rejects_caller_transaction_without_touching_it() -> None:
    session = _FakeSession(active=True)
    runner = _calendar_runner(session, [_calendar_payload(request_id="must-not-fetch")])

    with pytest.raises(ThsHistoryError) as error:
        await runner.sync_calendar(apply=True)

    assert error.value.code == "CALENDAR_PUBLICATION_REQUIRES_CLEAN_SESSION"
    assert session.in_transaction()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.begin.assert_not_awaited()
    session.begin_nested.assert_not_called()
    runner._catalog.resolve_primary.assert_not_awaited()
    runner.ensure_control_plane.assert_not_awaited()
    runner._store.ensure_source_authorization_before_provider_io.assert_not_awaited()
    runner._downloader.fetch_ths_json.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_venue", ["CN-SSE", "CN-SZSE", "CN-BJSE"])
async def test_daily_dump_authorizes_each_market_before_global_download(
    denied_venue: str,
) -> None:
    runner = object.__new__(ThsHistoryRunner)
    runner._session = SimpleNamespace(rollback=AsyncMock())
    runner._catalog = SimpleNamespace(
        resolve_primary=AsyncMock(return_value=_storage(THS_DAILY_K_DATASET_CODE))
    )
    checked_venues: list[str] = []

    async def check_authorization(context: object, authorization: object, **kwargs: object) -> None:
        venue = context.identity.venue
        checked_venues.append(venue)
        if venue == denied_venue:
            raise RuntimeError("source grant revoked")

    runner._store = SimpleNamespace(
        ensure_source_authorization_before_provider_io=AsyncMock(side_effect=check_authorization)
    )
    fetch = Mock(return_value=b"not consumed")
    runner._downloader = SimpleNamespace(fetch_dump=fetch)
    runner.ensure_control_plane = AsyncMock(return_value=object())
    runner._venue_authorizations = Mock(
        return_value={venue: _authorization(venue) for venue in ("CN-SSE", "CN-SZSE", "CN-BJSE")}
    )

    with pytest.raises(RuntimeError, match="source grant revoked"):
        await runner._collect_dump(
            dump_kind="daily-k",
            history_days=20,
            limit=None,
            as_of=datetime(2026, 9, 21, tzinfo=timezone.utc),
            cache_path=None,
            commit_every=None,
            skip_existing=False,
        )

    expected_venues = ["CN-SSE", "CN-SZSE", "CN-BJSE"]
    assert checked_venues == expected_venues[: expected_venues.index(denied_venue) + 1]
    calls = runner._store.ensure_source_authorization_before_provider_io.await_args_list
    for call, venue in zip(calls, checked_venues, strict=True):
        context, authorization = call.args
        assert context.identity.venue == venue
        assert context.query.dataset_code == THS_DAILY_K_DATASET_CODE
        assert context.query.data_kind == "bars"
        assert authorization.market == venue
        assert call.kwargs["provider_id"] == THS_DUMP_PROVIDER_ID
        assert call.kwargs["checked_at"].tzinfo is not None
    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_daily_dump_failure_rolls_back_only_its_symbol_and_keeps_prior_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = object.__new__(ThsHistoryRunner)
    session = _FakeSession()
    runner._session = session
    runner._catalog = SimpleNamespace(
        resolve_primary=AsyncMock(return_value=_storage(THS_DAILY_K_DATASET_CODE))
    )
    runner._store = SimpleNamespace(ensure_source_authorization_before_provider_io=AsyncMock())
    runner._downloader = SimpleNamespace(fetch_dump=Mock(return_value=b"fixture"))
    runner.ensure_control_plane = AsyncMock(return_value=object())
    runner._venue_authorizations = Mock(
        return_value={venue: _authorization(venue) for venue in ("CN-SSE", "CN-SZSE", "CN-BJSE")}
    )

    async def import_daily_k(
        *,
        bars_by_symbol: dict[str, list[object]],
        source_authorization: MarketDataSourceAuthorization,
        retrieved_at: datetime,
        window_start: datetime,
        window_end: datetime,
    ) -> list[SimpleNamespace]:
        symbol = next(iter(bars_by_symbol))
        if symbol == "600519.SH":
            raise RuntimeError("fixture failure")
        return [SimpleNamespace(passing_observation_count=7)]

    runner._importer = SimpleNamespace(import_daily_k=AsyncMock(side_effect=import_daily_k))
    monkeypatch.setattr(ths_history_runner_module, "parse_daily_k_parquet", lambda _: [object()])
    monkeypatch.setattr(
        ths_history_runner_module,
        "group_by_symbol",
        lambda _: {"000001.SZ": [object()], "600519.SH": [object()]},
    )

    report = await runner._collect_dump(
        dump_kind="daily-k",
        history_days=20,
        limit=None,
        as_of=datetime(2026, 9, 21, tzinfo=timezone.utc),
        cache_path=None,
        commit_every=None,
        skip_existing=False,
    )

    assert report.persisted_symbol_count == 1
    assert report.persisted_observation_count == 7
    assert report.skipped_symbol_count == 1
    assert len(session.savepoints) == 2
    session.savepoints[0].commit.assert_awaited_once_with()
    session.savepoints[0].rollback.assert_not_awaited()
    session.savepoints[1].rollback.assert_awaited_once_with()
    session.savepoints[1].commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_dump_savepoint_rolls_back_only_failed_symbol_in_sqlite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("CREATE TABLE ths_iteration200_symbols (symbol TEXT PRIMARY KEY)")
            )
        sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sessions() as session:
            runner = object.__new__(ThsHistoryRunner)
            runner._session = session
            runner._catalog = SimpleNamespace(
                resolve_primary=AsyncMock(return_value=_storage(THS_DAILY_K_DATASET_CODE))
            )
            runner._store = SimpleNamespace(
                ensure_source_authorization_before_provider_io=AsyncMock()
            )
            runner._downloader = SimpleNamespace(fetch_dump=Mock(return_value=b"fixture"))
            runner.ensure_control_plane = AsyncMock(return_value=object())
            runner._venue_authorizations = Mock(
                return_value={
                    venue: _authorization(venue) for venue in ("CN-SSE", "CN-SZSE", "CN-BJSE")
                }
            )

            async def import_daily_k(
                *,
                bars_by_symbol: dict[str, list[object]],
                source_authorization: MarketDataSourceAuthorization,
                retrieved_at: datetime,
                window_start: datetime,
                window_end: datetime,
            ) -> list[SimpleNamespace]:
                symbol = next(iter(bars_by_symbol))
                await session.execute(
                    text("INSERT INTO ths_iteration200_symbols (symbol) VALUES (:symbol)"),
                    {"symbol": symbol},
                )
                if symbol == "600519.SH":
                    raise RuntimeError("fixture failure")
                return [SimpleNamespace(passing_observation_count=7)]

            runner._importer = SimpleNamespace(import_daily_k=AsyncMock(side_effect=import_daily_k))
            monkeypatch.setattr(
                ths_history_runner_module, "parse_daily_k_parquet", lambda _: [object()]
            )
            monkeypatch.setattr(
                ths_history_runner_module,
                "group_by_symbol",
                lambda _: {"000001.SZ": [object()], "600519.SH": [object()]},
            )

            report = await runner._collect_dump(
                dump_kind="daily-k",
                history_days=20,
                limit=None,
                as_of=datetime(2026, 9, 21, tzinfo=timezone.utc),
                cache_path=None,
                commit_every=None,
                skip_existing=False,
            )

            rows = (
                (
                    await session.execute(
                        text("SELECT symbol FROM ths_iteration200_symbols ORDER BY symbol")
                    )
                )
                .scalars()
                .all()
            )
            assert list(rows) == ["000001.SZ"]
            assert report.persisted_symbol_count == 1
            assert report.persisted_observation_count == 7
            assert report.skipped_symbol_count == 1
            assert session.in_transaction()

            await session.rollback()
            rolled_back_rows = (
                (await session.execute(text("SELECT symbol FROM ths_iteration200_symbols")))
                .scalars()
                .all()
            )
            assert list(rolled_back_rows) == []
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["adjustment", "financial"])
async def test_reference_failure_rolls_back_only_its_symbol_and_keeps_prior_count(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    dataset_code = (
        THS_ADJUSTMENT_FACTORS_DATASET_CODE
        if operation == "adjustment"
        else THS_FINANCIALS_STATEMENTS["income"]
    )
    runner = object.__new__(ThsHistoryRunner)
    session = _FakeSession()
    runner._session = session
    runner._catalog = SimpleNamespace(
        resolve_primary=AsyncMock(return_value=_storage(dataset_code))
    )
    runner._store = SimpleNamespace(ensure_source_authorization_before_provider_io=AsyncMock())
    runner._downloader = SimpleNamespace(
        fetch_ths_json=Mock(return_value={"code": 0, "data": {"item": []}})
    )
    runner.ensure_control_plane = AsyncMock(return_value=object())
    runner._venue_authorizations = Mock(
        return_value={"CN-SSE": _authorization("CN-SSE"), "CN-SZSE": _authorization("CN-SZSE")}
    )

    async def persist_reference(**kwargs: object) -> None:
        calls = (
            collector.persist_adjustment_factors
            if operation == "adjustment"
            else collector.persist_financials
        )
        if calls.await_count == 2:
            raise RuntimeError("fixture failure")

    collector = SimpleNamespace(
        persist_adjustment_factors=AsyncMock(side_effect=persist_reference),
        persist_financials=AsyncMock(side_effect=persist_reference),
    )
    monkeypatch.setattr(
        ths_reference_collector_module,
        "ThsReferenceCollector",
        Mock(return_value=collector),
    )

    if operation == "adjustment":
        report = await runner.backfill_adjustment_factors(
            symbols=["000001.SZ", "600519.SH"],
            commit_every=None,
        )
    else:
        report = await runner.backfill_financials(
            statement="income",
            symbols=["000001.SZ", "600519.SH"],
            commit_every=None,
        )

    assert report["persisted_symbol_count"] == 1
    assert report["failed_count"] == 1
    assert report["failed_samples"] == ["600519.SH:RuntimeError"]
    assert len(session.savepoints) == 2
    session.savepoints[0].commit.assert_awaited_once_with()
    session.savepoints[0].rollback.assert_not_awaited()
    session.savepoints[1].rollback.assert_awaited_once_with()
    session.savepoints[1].commit.assert_not_awaited()
    session.rollback.assert_not_awaited()


def _patch_cli_runtime(
    monkeypatch: pytest.MonkeyPatch,
    cli: ModuleType,
    runner: SimpleNamespace,
) -> tuple[_FakeSession, SimpleNamespace]:
    session = _FakeSession()
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(cli, "create_async_engine", Mock(return_value=engine))
    monkeypatch.setattr(
        cli,
        "async_sessionmaker",
        Mock(return_value=Mock(return_value=session)),
    )
    monkeypatch.setattr(
        cli.ThsHistoryRunner,
        "from_environment",
        Mock(return_value=runner),
    )
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///fixture.db")
    return session, engine


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_backfill_cli_calendar_uses_explicit_apply_mode(
    monkeypatch: pytest.MonkeyPatch,
    apply: bool,
) -> None:
    runner = SimpleNamespace(sync_calendar=AsyncMock(return_value=1))
    session, engine = _patch_cli_runtime(monkeypatch, backfill_ths_history, runner)
    argv = ["--dataset", "calendar"] + (["--apply"] if apply else [])

    results = await backfill_ths_history._run(backfill_ths_history._arguments(argv))

    assert results == {"calendar": {"calendar_event_count": 1}}
    runner.sync_calendar.assert_awaited_once_with(apply=apply)
    engine.dispose.assert_awaited_once_with()
    if apply:
        session.commit.assert_awaited_once_with()
        session.rollback.assert_not_awaited()
    else:
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_backfill_cli_commits_prior_dataset_before_apply_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = SimpleNamespace(backfill_daily_k=AsyncMock(), sync_calendar=AsyncMock())
    session, _ = _patch_cli_runtime(monkeypatch, backfill_ths_history, runner)
    report = SimpleNamespace(
        dump_kind="daily-k",
        parsed_row_count=3,
        symbol_count=2,
        persisted_symbol_count=1,
        persisted_observation_count=4,
    )

    async def backfill_daily_k(
        *, limit: int | None, cache_path: str, commit_every: int | None, skip_existing: bool
    ) -> SimpleNamespace:
        assert commit_every == 200
        session.active = True
        return report

    async def sync_calendar(*, apply: bool) -> int:
        assert apply is True
        assert not session.in_transaction()
        return 1

    runner.backfill_daily_k.side_effect = backfill_daily_k
    runner.sync_calendar.side_effect = sync_calendar

    results = await backfill_ths_history._run(
        backfill_ths_history._arguments(
            ["--dataset", "daily-k", "--dataset", "calendar", "--apply"]
        )
    )

    assert results["calendar"] == {"calendar_event_count": 1}
    runner.sync_calendar.assert_awaited_once_with(apply=True)
    assert session.commit.await_count == 2
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("apply", [False, True])
async def test_daily_cli_calendar_uses_explicit_apply_mode(
    monkeypatch: pytest.MonkeyPatch,
    apply: bool,
) -> None:
    runner = SimpleNamespace(collect_daily=AsyncMock(), sync_calendar=AsyncMock())
    session, engine = _patch_cli_runtime(monkeypatch, collect_ths_daily, runner)
    argv = ["--apply"] if apply else []

    async def collect_daily(*, limit: int | None, commit_every: int | None) -> SimpleNamespace:
        assert commit_every == (200 if apply else None)
        if apply:
            session.active = True
        return SimpleNamespace(
            dump_kind="daily-k-10d",
            parsed_row_count=3,
            symbol_count=2,
            persisted_symbol_count=1,
            persisted_observation_count=4,
        )

    async def sync_calendar(*, apply: bool) -> int:
        assert apply is expected_apply
        if apply:
            assert not session.in_transaction()
        return 1

    runner.collect_daily.side_effect = collect_daily
    runner.sync_calendar.side_effect = sync_calendar
    expected_apply = apply

    results = await collect_ths_daily._run(collect_ths_daily._arguments(argv))

    assert results == {
        "daily_k": {
            "dump_kind": "daily-k-10d",
            "parsed_row_count": 3,
            "symbol_count": 2,
            "persisted_symbol_count": 1,
            "persisted_observation_count": 4,
        },
        "calendar": {"calendar_event_count": 1},
    }
    runner.sync_calendar.assert_awaited_once_with(apply=apply)
    engine.dispose.assert_awaited_once_with()
    if apply:
        assert session.commit.await_count == 2
        session.rollback.assert_not_awaited()
    else:
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dataset", "method_name", "interval"),
    [
        ("daily-k", "backfill_daily_k", 200),
        ("adjustment-factors", "backfill_adjustment_factors", 100),
        ("financials-income", "backfill_financials", 100),
        ("financials-balance", "backfill_financials", 100),
        ("financials-cashflow", "backfill_financials", 100),
    ],
)
@pytest.mark.parametrize("apply", [False, True])
async def test_backfill_cli_selects_commit_interval_by_apply_mode(
    monkeypatch: pytest.MonkeyPatch,
    dataset: str,
    method_name: str,
    interval: int,
    apply: bool,
) -> None:
    report = SimpleNamespace(
        dump_kind="daily-k",
        parsed_row_count=1,
        symbol_count=1,
        persisted_symbol_count=0,
        persisted_observation_count=0,
    )
    runner = SimpleNamespace(
        backfill_daily_k=AsyncMock(return_value=report),
        backfill_adjustment_factors=AsyncMock(return_value={"persisted_symbol_count": 0}),
        backfill_financials=AsyncMock(return_value={"persisted_symbol_count": 0}),
    )
    session, _ = _patch_cli_runtime(monkeypatch, backfill_ths_history, runner)
    argv = ["--dataset", dataset] + (["--apply"] if apply else [])

    await backfill_ths_history._run(backfill_ths_history._arguments(argv))

    method = getattr(runner, method_name)
    method.assert_awaited_once()
    assert method.await_args.kwargs["commit_every"] == (interval if apply else None)
    if apply:
        session.commit.assert_awaited_once_with()
        session.rollback.assert_not_awaited()
    else:
        session.commit.assert_not_awaited()
        session.rollback.assert_awaited_once_with()
