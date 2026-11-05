"""Contract tests for the settings section split (``app.settings`` mixins).

``app.config.Settings`` composes the section modules into one model. These tests
pin the invariants the split is only allowed to hold: the composed class exposes
every section, a field belongs to exactly one section, the validators declared on
a section mixin really run on the composed model, env-var names are unchanged, and
the repo root the defaults and the ``.env`` search are derived from is still the
one ``app/config.py`` sits in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

from app import config as config_module
from app.config import Settings, get_settings
from app.settings import (
    AiAssistantSettingsMixin,
    AiResearchV2SettingsMixin,
    ApplicationSettingsMixin,
    AssetResearchSettingsMixin,
    BrokerAccountSettingsMixin,
    DatabaseSettingsMixin,
    MarketDataSettingsMixin,
    OperationsSettingsMixin,
    SecurityAuthSettingsMixin,
    ServiceDeploymentSecretsMixin,
)
from app.settings.paths import DEFAULT_SQLITE_DATABASE_URL, REPO_ROOT

SECTION_MIXINS = (
    ApplicationSettingsMixin,
    SecurityAuthSettingsMixin,
    DatabaseSettingsMixin,
    MarketDataSettingsMixin,
    AssetResearchSettingsMixin,
    AiResearchV2SettingsMixin,
    AiAssistantSettingsMixin,
    ServiceDeploymentSecretsMixin,
    OperationsSettingsMixin,
    BrokerAccountSettingsMixin,
)


def test_settings_composes_every_section() -> None:
    """Every section mixin is a base of the composed model, which is a BaseSettings."""
    for mixin in SECTION_MIXINS:
        assert mixin in Settings.__mro__, mixin
    assert BaseSettings in Settings.__mro__
    assert Settings.__module__ == "app.config"


def test_every_field_belongs_to_exactly_one_section() -> None:
    """No field is declared twice and none is dropped by the composition."""
    owners: dict[str, list[str]] = {}
    for mixin in SECTION_MIXINS:
        for name in getattr(mixin, "__annotations__", {}):
            owners.setdefault(name, []).append(mixin.__name__)
    assert sorted(owners) == sorted(Settings.model_fields)
    duplicated = {name: chain for name, chain in owners.items() if len(chain) > 1}
    assert duplicated == {}


def test_repo_root_derivation_still_points_at_the_repository() -> None:
    """``app.settings.paths`` sits one level deeper than ``app/config.py``."""
    assert REPO_ROOT == Path(config_module.__file__).resolve().parents[3]
    assert Settings.model_fields["DATABASE_URL"].default == DEFAULT_SQLITE_DATABASE_URL
    assert Settings.model_fields["DATABASE_URL"].default == (
        f"sqlite+aiosqlite:///{(REPO_ROOT / 'data' / 'dev' / 'backtrader.db').as_posix()}"
    )
    assert Settings.model_fields["MARKET_DATA_RESEARCH_ARTIFACT_ROOT"].default == str(
        (REPO_ROOT / "data" / "market_data_research").resolve()
    )


def test_env_file_search_root_uses_the_shared_repo_root() -> None:
    """The ``.env`` search is still the cwd file plus the repository-root file.

    Three suites assign ``Settings.model_config["env_file"] = None`` at import time so a
    developer ``.env`` cannot leak into their assertions; when one of them has run first
    the composition itself is still pinned by the tests above, so this one reports why it
    cannot speak instead of failing on another suite's global state.
    """
    env_file = Settings.model_config.get("env_file")
    if env_file is None:
        pytest.skip("another suite disabled the .env search path for its assertions")
    assert env_file[0] == ".env"
    assert env_file[1] == str(REPO_ROOT / ".env")


def test_section_field_validators_fire_on_the_composed_model() -> None:
    """A ``field_validator`` declared on a mixin is collected by pydantic and runs."""
    with pytest.raises(ValidationError, match="Unsupported DATABASE_TYPE"):
        Settings(_env_file=None, DATABASE_TYPE="mongodb")
    with pytest.raises(ValidationError, match="MARKET_DATA_OPENBB_PROVIDER must be one of"):
        Settings(_env_file=None, MARKET_DATA_OPENBB_PROVIDER="not-a-provider")
    with pytest.raises(ValidationError, match="exceeds the 256 KiB limit"):
        Settings(_env_file=None, SERVICE_READ_DEPLOYMENT_JSON="x" * 262_145)
    with pytest.raises(ValidationError, match="AI_BUDGET_MODE must be one of"):
        Settings(_env_file=None, AI_BUDGET_MODE="medium")
    with pytest.raises(ValidationError, match="PORT must be between 1 and 65535"):
        Settings(_env_file=None, PORT=99_999)


def test_section_validators_keep_normalizing_values() -> None:
    settings = Settings(
        _env_file=None,
        DATABASE_TYPE="PostgreSQL",
        AKSHARE_INTERFACE_BOOTSTRAP_MODE=" REFRESH ",
        MARKET_DATA_OPENBB_ALLOWED_MARKETS="CN, cn, US,",
    )
    assert settings.DATABASE_TYPE == "postgresql"
    assert settings.AKSHARE_INTERFACE_BOOTSTRAP_MODE == "refresh"
    assert settings.MARKET_DATA_OPENBB_ALLOWED_MARKETS == "CN,cn,US"


def test_composed_model_validator_still_spans_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    """The after-validator that reads fields from several sections still trips."""
    monkeypatch.delenv("DEBUG", raising=False)
    with pytest.raises(ValidationError, match="MARKET_DATA_CURSOR_SIGNING_KEY is required"):
        Settings(_env_file=None, MARKET_DATA_QUERY_V2_ENABLED=True)


def test_env_var_names_are_unchanged_and_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sectioning the fields did not change the env keys they read from."""
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("akshare_data_database_url", "mysql+aiomysql://env/warehouse")
    monkeypatch.setenv("STOCK_SIGNAL_SCHEDULE_ENABLED", "true")
    settings = Settings(_env_file=None)
    assert settings.AKSHARE_DATA_DATABASE_URL == "mysql+aiomysql://env/warehouse"
    assert settings.STOCK_SIGNAL_SCHEDULE_ENABLED is True


def test_secret_fields_stay_out_of_repr_and_dump() -> None:
    settings = Settings(_env_file=None)
    assert "SERVICE_READ_DEPLOYMENT_JSON" not in repr(settings)
    assert "SERVICE_READ_DEPLOYMENT_JSON" not in settings.model_dump()
    assert "MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY" not in repr(settings)


def test_facade_import_surface_is_preserved() -> None:
    """What the rest of the codebase imports from ``app.config`` still resolves."""
    for name in (
        "Settings",
        "get_settings",
        "production_security_mode",
        "_DEFAULT_SECRETS",
        "_DEFAULT_PASSWORDS",
        "_coerce_bool",
        "_is_production",
        "_settings",
    ):
        assert hasattr(config_module, name), name


def test_get_settings_keeps_the_resettable_module_singleton() -> None:
    assert get_settings() is get_settings()
    assert isinstance(get_settings(), Settings)
