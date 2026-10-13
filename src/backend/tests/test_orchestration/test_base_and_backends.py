"""
Acceptance tests for Task 2 & 6: Backend abstraction, APScheduler adapter, detector.

Validates Requirements: 6.1, 6.2, 6.3, 6.4, 6.6
"""

from collections.abc import Iterator
from types import ModuleType

import pytest


@pytest.fixture
def isolated_settings_cache() -> Iterator[ModuleType]:
    """Reset settings for a detector test without invalidating app imports."""
    import app.config as config_module
    import app.db.database as database_module
    import app.main as main_module

    application_settings = config_module._settings
    assert application_settings is not None
    assert main_module.settings is application_settings
    assert database_module.settings is application_settings

    with pytest.MonkeyPatch.context() as cache_patch:
        cache_patch.setattr(config_module, "_settings", None)
        yield config_module

    assert config_module._settings is application_settings
    assert main_module.settings is application_settings
    assert database_module.settings is application_settings


class TestOrchestratorBackendInterface:
    """AT-6.6: OrchestratorBackend defines required abstract methods."""

    def test_cannot_instantiate_abstract_class(self):
        from app.services.orchestration.base import OrchestratorBackend

        with pytest.raises(TypeError):
            OrchestratorBackend()

    def test_abstract_methods_defined(self):
        from app.services.orchestration.base import OrchestratorBackend

        abstract_methods = OrchestratorBackend.__abstractmethods__
        expected = {
            "start",
            "shutdown",
            "add_or_update_task",
            "remove_task",
            "run_task_now",
            "reload_active_tasks",
            "get_backend_status",
        }
        assert expected == abstract_methods


class TestAPSchedulerBackend:
    """AT-2.1: APSchedulerBackend implements OrchestratorBackend."""

    def test_is_orchestrator_backend(self):
        from app.services.orchestration.apscheduler_backend import APSchedulerBackend
        from app.services.orchestration.base import OrchestratorBackend

        backend = APSchedulerBackend()
        assert isinstance(backend, OrchestratorBackend)

    async def test_get_backend_status_format(self):
        from app.services.orchestration.apscheduler_backend import APSchedulerBackend

        backend = APSchedulerBackend()
        status = await backend.get_backend_status()
        assert status["type"] == "apscheduler"
        assert "running" in status
        assert "job_count" in status
        assert isinstance(status["running"], bool)
        assert isinstance(status["job_count"], int)


class TestBackendDetector:
    """AT-6.1 to AT-6.4: Backend auto-detection logic."""

    async def test_auto_detect_no_airflow_url_uses_apscheduler(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_settings_cache: ModuleType,
    ) -> None:
        """When AIRFLOW_API_BASE_URL is empty, auto mode selects APScheduler."""
        monkeypatch.setenv("ORCHESTRATION_BACKEND", "auto")
        monkeypatch.setenv("AIRFLOW_API_BASE_URL", "")

        from app.services.orchestration.apscheduler_backend import APSchedulerBackend
        from app.services.orchestration.detector import BackendDetector

        detector = BackendDetector()
        backend = await detector.detect()
        assert isinstance(backend, APSchedulerBackend)

    async def test_forced_apscheduler(
        self, monkeypatch: pytest.MonkeyPatch, isolated_settings_cache: ModuleType
    ) -> None:
        """ORCHESTRATION_BACKEND=apscheduler forces APScheduler."""
        monkeypatch.setenv("ORCHESTRATION_BACKEND", "apscheduler")

        from app.services.orchestration.apscheduler_backend import APSchedulerBackend
        from app.services.orchestration.detector import BackendDetector

        detector = BackendDetector()
        backend = await detector.detect()
        assert isinstance(backend, APSchedulerBackend)

    async def test_forced_airflow_no_url_fallback(
        self, monkeypatch: pytest.MonkeyPatch, isolated_settings_cache: ModuleType
    ) -> None:
        """ORCHESTRATION_BACKEND=airflow but no URL falls back to APScheduler."""
        monkeypatch.setenv("ORCHESTRATION_BACKEND", "airflow")
        monkeypatch.setenv("AIRFLOW_API_BASE_URL", "")

        from app.services.orchestration.apscheduler_backend import APSchedulerBackend
        from app.services.orchestration.detector import BackendDetector

        detector = BackendDetector()
        backend = await detector.detect()
        assert isinstance(backend, APSchedulerBackend)

    async def test_auto_detect_airflow_unreachable_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_settings_cache: ModuleType,
    ) -> None:
        """Auto mode with unreachable Airflow URL falls back to APScheduler."""
        monkeypatch.setenv("ORCHESTRATION_BACKEND", "auto")
        monkeypatch.setenv("AIRFLOW_API_BASE_URL", "http://127.0.0.1:19999/api/v1")
        monkeypatch.setenv("AIRFLOW_PASSWORD", "test")

        from app.services.orchestration.apscheduler_backend import APSchedulerBackend
        from app.services.orchestration.detector import BackendDetector

        detector = BackendDetector()
        backend = await detector.detect()
        assert isinstance(backend, APSchedulerBackend)


def test_settings_cache_reset_restores_already_imported_modules(
    isolated_settings_cache: ModuleType,
) -> None:
    """A fresh cache entry must not leave already-imported modules stale afterward."""
    import app.main as main_module

    replacement_settings = isolated_settings_cache.get_settings()
    assert replacement_settings is not main_module.settings
