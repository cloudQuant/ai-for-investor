"""Iteration 204: the AkShare scheduler handoff in ``app.startup.orchestration``.

The API process may arm the AkShare APScheduler only when the orchestration backend
fails *and* ``AKSHARE_SCHEDULER_API_FALLBACK`` explicitly allows it. These tests pin the
three arms of that rule (allow / forbid / unrecognised) and the observable arming plane
recorded on ``app.state``. No real scheduler, backend or database is touched.
"""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.startup import orchestration
from app.startup.orchestration import (
    SCHEDULER_START_SOURCE_API_FALLBACK,
    SCHEDULER_START_SOURCE_ORCHESTRATION,
)

_FALLBACK_SETTING = "AKSHARE_SCHEDULER_API_FALLBACK"
_ORCHESTRATION_ERROR = "airflow health check failed"


class RecordingLogger:
    """Startup logger double that keeps the level of every message."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def _record(self, level: str, message: object, *args: object) -> None:
        text = str(message)
        if args:
            text = f"{text} {' '.join(str(arg) for arg in args)}"
        self.records.append((level, text))

    def debug(self, message: object, *args: object) -> None:
        self._record("debug", message, *args)

    def info(self, message: object, *args: object) -> None:
        self._record("info", message, *args)

    def warning(self, message: object, *args: object) -> None:
        self._record("warning", message, *args)

    def error(self, message: object, *args: object) -> None:
        self._record("error", message, *args)

    def exception(self, message: object, *args: object) -> None:
        self._record("exception", message, *args)

    def messages(self, level: str) -> list[str]:
        return [text for recorded_level, text in self.records if recorded_level == level]

    def has(self, level: str, needle: str) -> bool:
        return any(needle in text for text in self.messages(level))


class FakeAkshareSchedulerService:
    def __init__(self) -> None:
        self.start_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def shutdown(self) -> None:
        return None


class SchedulerGetter:
    """Getter double that also counts how often the fallback path asked for it."""

    def __init__(self, service: FakeAkshareSchedulerService) -> None:
        self.service = service
        self.calls = 0

    def __call__(self) -> FakeAkshareSchedulerService:
        self.calls += 1
        return self.service


class FakeOrchestrationBackend:
    def __init__(self, *, fail: bool) -> None:
        self._fail = fail
        self.start_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def get_backend_status(self) -> dict[str, object]:
        return {"type": "apscheduler"}


class Detector:
    """``BackendDetector`` double; ``raise_on_start`` makes the backend construction fail."""

    def __init__(self, *, raise_on_start: bool) -> None:
        self._raise_on_start = raise_on_start
        self.backend: FakeOrchestrationBackend | None = None

    def __call__(self) -> "Detector":
        return self

    async def detect(self) -> FakeOrchestrationBackend:
        self.backend = FakeOrchestrationBackend(fail=self._raise_on_start)
        if self._raise_on_start:
            raise RuntimeError(_ORCHESTRATION_ERROR)
        return self.backend


class FakeThsScheduler:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        return None

    @classmethod
    def from_settings(cls, settings: object) -> "FakeThsScheduler":
        return cls()

    async def start(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def describe(self) -> dict[str, object]:
        return {"enabled": False}


@pytest.fixture(autouse=True)
def _no_real_ths_scheduler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.market_data.ths_scheduler.ThsMarketDataScheduler",
        FakeThsScheduler,
        raising=True,
    )


def _make_app() -> tuple[FastAPI, RecordingLogger]:
    startup_logger = RecordingLogger()
    app = FastAPI()
    app.state.startup_logger = startup_logger
    return app, startup_logger


def _make_settings(
    *,
    fallback: object = "allow",
    database_url: str = "sqlite+aiosqlite:///akshare-warehouse-not-opened.db",
) -> SimpleNamespace:
    return SimpleNamespace(
        AKSHARE_DATA_DATABASE_URL=database_url,
        **{_FALLBACK_SETTING: fallback},
    )


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    detector: Detector,
    scheduler_service: FakeAkshareSchedulerService,
) -> SchedulerGetter:
    getter = SchedulerGetter(scheduler_service)
    monkeypatch.setattr(
        "app.services.orchestration.detector.BackendDetector", detector, raising=True
    )
    monkeypatch.setattr(
        "app.api.airflow_dags.set_orchestration_backend", lambda backend: None, raising=True
    )
    monkeypatch.setattr(
        "app.services.akshare.scheduler_service.get_akshare_scheduler_service",
        getter,
        raising=True,
    )
    return getter


def _marker(app: FastAPI) -> object:
    return getattr(app.state, orchestration.SCHEDULER_START_SOURCE_ATTR, None)


@pytest.mark.asyncio
async def test_fallback_allowed_and_orchestration_fails_arms_scheduler_with_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, startup_logger = _make_app()
    scheduler_service = FakeAkshareSchedulerService()
    getter = _wire(
        monkeypatch,
        detector=Detector(raise_on_start=True),
        scheduler_service=scheduler_service,
    )

    await orchestration.register(app, _make_settings(fallback="allow"))

    assert getter.calls == 1
    assert scheduler_service.start_calls == 1
    assert app.state.akshare_scheduler_service is scheduler_service
    assert _marker(app) == SCHEDULER_START_SOURCE_API_FALLBACK
    # The arming plane is announced at WARNING, not info, and carries the root cause.
    assert startup_logger.has("warning", "Fallback: Akshare APScheduler started directly")
    assert not startup_logger.has("info", "Fallback: Akshare APScheduler started directly")
    assert any(_ORCHESTRATION_ERROR in text for text in startup_logger.messages("warning"))
    # The pre-existing orchestration failure log is kept.
    assert startup_logger.has("exception", "Failed to start orchestration backend")


@pytest.mark.asyncio
async def test_fallback_forbidden_suppresses_scheduler_and_records_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, startup_logger = _make_app()
    scheduler_service = FakeAkshareSchedulerService()
    getter = _wire(
        monkeypatch,
        detector=Detector(raise_on_start=True),
        scheduler_service=scheduler_service,
    )

    await orchestration.register(app, _make_settings(fallback="forbid"))

    assert getter.calls == 0
    assert scheduler_service.start_calls == 0
    assert not hasattr(app.state, "akshare_scheduler_service")
    assert _marker(app) is None
    assert not startup_logger.messages("warning")
    assert startup_logger.has("error", _FALLBACK_SETTING)
    assert startup_logger.has("error", "Akshare APScheduler not started")


@pytest.mark.asyncio
async def test_unrecognised_fallback_value_fails_closed_like_forbid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, startup_logger = _make_app()
    scheduler_service = FakeAkshareSchedulerService()
    getter = _wire(
        monkeypatch,
        detector=Detector(raise_on_start=True),
        scheduler_service=scheduler_service,
    )

    # A typo must not silently behave like "allow": it decides who writes the warehouse.
    await orchestration.register(app, _make_settings(fallback="allows"))

    assert getter.calls == 0
    assert scheduler_service.start_calls == 0
    assert _marker(app) is None
    assert not startup_logger.messages("warning")
    assert startup_logger.has("error", "fail-closed")
    assert startup_logger.has("error", _FALLBACK_SETTING)


@pytest.mark.asyncio
async def test_fallback_value_is_matched_case_and_whitespace_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, startup_logger = _make_app()
    scheduler_service = FakeAkshareSchedulerService()
    _wire(
        monkeypatch,
        detector=Detector(raise_on_start=True),
        scheduler_service=scheduler_service,
    )

    await orchestration.register(app, _make_settings(fallback="  ALLOW  "))

    assert scheduler_service.start_calls == 1
    assert _marker(app) == SCHEDULER_START_SOURCE_API_FALLBACK
    assert not startup_logger.messages("error")


@pytest.mark.asyncio
async def test_orchestration_success_marks_orchestration_plane_and_skips_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, startup_logger = _make_app()
    scheduler_service = FakeAkshareSchedulerService()
    getter = _wire(
        monkeypatch,
        detector=Detector(raise_on_start=False),
        scheduler_service=scheduler_service,
    )

    await orchestration.register(app, _make_settings(fallback="allow"))

    assert _marker(app) == SCHEDULER_START_SOURCE_ORCHESTRATION
    # The fallback path was not taken at all.
    assert getter.calls == 0
    assert scheduler_service.start_calls == 0
    assert not hasattr(app.state, "akshare_scheduler_service")
    assert not startup_logger.messages("warning")
    assert not startup_logger.messages("error")
    assert startup_logger.has("info", "Orchestration backend started")


@pytest.mark.asyncio
async def test_missing_warehouse_url_returns_before_any_scheduler_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, startup_logger = _make_app()
    scheduler_service = FakeAkshareSchedulerService()
    detector = Detector(raise_on_start=False)
    getter = _wire(monkeypatch, detector=detector, scheduler_service=scheduler_service)

    await orchestration.register(app, _make_settings(fallback="allow", database_url=""))

    assert detector.backend is None
    assert getter.calls == 0
    assert scheduler_service.start_calls == 0
    assert _marker(app) is None
    assert not hasattr(app.state, "akshare_scheduler_service")
    assert not startup_logger.messages("warning")
    assert not startup_logger.messages("error")


@pytest.mark.asyncio
async def test_settings_default_keeps_current_single_scheduler_host_behaviour() -> None:
    from app.config import get_settings

    settings = get_settings()

    assert getattr(settings, _FALLBACK_SETTING) == "allow"
