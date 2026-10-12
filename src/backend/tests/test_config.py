"""
Configuration module tests.
"""

import json
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.config_parsing import parse_ai_providers, parse_strategy_score_weights


class TestConfig:
    """Configuration tests."""

    def test_get_settings_returns_settings(self):
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_default_values(self, monkeypatch):
        """Defaults do not inherit a developer's dotenv schema flags."""
        monkeypatch.delenv("AI_PROVIDERS", raising=False)
        monkeypatch.delenv("STRATEGY_SCORE_WEIGHTS", raising=False)
        monkeypatch.delenv("DB_AUTO_CREATE_SCHEMA", raising=False)
        monkeypatch.delenv("DB_AUTO_CREATE_DEFAULT_ADMIN", raising=False)
        monkeypatch.delenv("AI_RESEARCH_PROTOCOL_V2_WORKFLOW_VERSION", raising=False)
        monkeypatch.delenv("AI_RESEARCH_PROTOCOL_V2_WORKER_ENABLED", raising=False)
        monkeypatch.delenv("AI_RESEARCH_PROTOCOL_V2_WORKER_FACTORY", raising=False)
        monkeypatch.delenv("AI_RESEARCH_PROTOCOL_V2_WORKER_POLL_SECONDS", raising=False)
        monkeypatch.delenv("MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED", raising=False)
        monkeypatch.delenv("MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED", raising=False)
        monkeypatch.delenv("MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY", raising=False)
        settings = Settings(_env_file=None, DEBUG=True)
        assert settings.APP_NAME == "ai-for-investor"
        assert settings.JWT_ALGORITHM == "HS256"
        assert settings.JWT_EXPIRE_MINUTES > 0
        assert settings.RATE_LIMIT_AUTH_ME == "60/minute"
        assert settings.PORT == 8000
        assert settings.DB_AUTO_CREATE_SCHEMA is False
        assert settings.DB_AUTO_CREATE_DEFAULT_ADMIN is False
        assert settings.AI_RESEARCH_PROTOCOL_V2_WORKFLOW_VERSION == "generation-v1"
        assert settings.AI_RESEARCH_PROTOCOL_V2_WORKER_ENABLED is False
        assert settings.AI_RESEARCH_PROTOCOL_V2_WORKER_FACTORY == ""
        assert settings.AI_RESEARCH_PROTOCOL_V2_WORKER_POLL_SECONDS == 10.0
        assert settings.MARKET_DATA_RESEARCH_CACHE_FILL_ENABLED is False
        assert settings.MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED is False
        assert "openai" in settings.AI_PROVIDERS
        assert "ollama" in settings.AI_PROVIDERS
        assert "volcengine_ark" in settings.AI_PROVIDERS
        assert "siliconflow" in settings.AI_PROVIDERS
        assert settings.STRATEGY_SCORE_WEIGHTS == {
            "profitability": 0.2,
            "risk_control": 0.2,
            "stability": 0.2,
            "overfitting_risk": 0.15,
            "executability": 0.15,
            "benchmark_comparison": 0.1,
        }

    def test_settings_singleton(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2  # lru_cache should return same instance

    def test_protocol_v2_workflow_setting_accepts_only_reviewed_graph_versions(self):
        """A deployment cannot accidentally select an unregistered persisted graph."""

        for workflow_version in ("generation-v1", "discovery-v1"):
            settings = Settings(
                _env_file=None,
                AI_RESEARCH_PROTOCOL_V2_WORKFLOW_VERSION=workflow_version,
            )
            assert settings.AI_RESEARCH_PROTOCOL_V2_WORKFLOW_VERSION == workflow_version

        with pytest.raises(ValidationError):
            Settings(_env_file=None, AI_RESEARCH_PROTOCOL_V2_WORKFLOW_VERSION="browser-v1")

    def test_market_data_v2_requires_an_operator_cursor_hmac_key(self):
        """The enabled local-first API cannot issue unsigned pagination tokens."""
        with pytest.raises(ValidationError, match="MARKET_DATA_CURSOR_SIGNING_KEY"):
            Settings(
                _env_file=None,
                DEBUG=True,
                MARKET_DATA_QUERY_V2_ENABLED=True,
            )

        settings = Settings(
            _env_file=None,
            DEBUG=True,
            MARKET_DATA_QUERY_V2_ENABLED=True,
            MARKET_DATA_CURSOR_SIGNING_KEY="x" * 32,
        )

        assert settings.MARKET_DATA_CURSOR_SIGNING_KEY == "x" * 32

    def test_market_data_research_backtest_bridge_requires_its_own_hmac_key_and_root(self):
        """The strict local-only bridge cannot be enabled by a browser flag alone."""
        with pytest.raises(ValidationError, match="MARKET_DATA_QUERY_V2_ENABLED"):
            Settings(
                _env_file=None,
                DEBUG=True,
                MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=True,
            )

        with pytest.raises(ValidationError, match="MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY"):
            Settings(
                _env_file=None,
                DEBUG=True,
                MARKET_DATA_QUERY_V2_ENABLED=True,
                MARKET_DATA_CURSOR_SIGNING_KEY="x" * 32,
                MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=True,
            )

        with pytest.raises(ValidationError, match="MARKET_DATA_RESEARCH_ARTIFACT_ROOT"):
            Settings(
                _env_file=None,
                DEBUG=True,
                MARKET_DATA_QUERY_V2_ENABLED=True,
                MARKET_DATA_CURSOR_SIGNING_KEY="x" * 32,
                MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=True,
                MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY="y" * 32,
                MARKET_DATA_RESEARCH_ARTIFACT_ROOT="relative-artifacts",
            )

        settings = Settings(
            _env_file=None,
            DEBUG=True,
            MARKET_DATA_QUERY_V2_ENABLED=True,
            MARKET_DATA_CURSOR_SIGNING_KEY="x" * 32,
            MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED=True,
            MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY="y" * 32,
            MARKET_DATA_RESEARCH_ARTIFACT_ROOT="/tmp/market-data-research-artifacts",
        )

        assert settings.MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_ENABLED is True

    def test_market_data_openbb_provider_uses_one_canonical_token_across_runtime_paths(self):
        """Mixed-case operator input cannot create a route/receipt provider-ID split."""
        settings = Settings(
            _env_file=None,
            DEBUG=True,
            MARKET_DATA_OPENBB_PROVIDER="YFinance",
        )

        assert settings.MARKET_DATA_OPENBB_PROVIDER == "yfinance"

        with pytest.raises(ValidationError, match="MARKET_DATA_OPENBB_PROVIDER"):
            Settings(
                _env_file=None,
                DEBUG=True,
                MARKET_DATA_OPENBB_PROVIDER="yfinance;unreviewed",
            )

        with pytest.raises(ValidationError, match="MARKET_DATA_OPENBB_PROVIDER"):
            Settings(
                _env_file=None,
                DEBUG=True,
                MARKET_DATA_OPENBB_PROVIDER="unreviewed-provider",
            )

    def test_ai_providers_can_be_loaded_from_json_string(self):
        settings = Settings(
            AI_PROVIDERS=(
                '{"local": {"base_url": "http://localhost:11434", '
                '"api_key_env": null, "models": ["ollama/qwen2.5-coder:7b"]}}'
            )
        )

        assert settings.AI_PROVIDERS["local"]["base_url"] == "http://localhost:11434"
        assert settings.AI_PROVIDERS["local"]["models"] == ["ollama/qwen2.5-coder:7b"]


def test_json_settings_parsers_preserve_dict_and_json_inputs() -> None:
    providers = {7: {"base_url": "http://localhost"}, "ignored": ["not-a-provider"]}

    parsed_providers = parse_ai_providers(providers)
    assert parsed_providers == {"7": {"base_url": "http://localhost"}}
    assert parsed_providers["7"] is not providers[7]
    assert parse_ai_providers('{"local": {"models": ["model-a"]}}') == {
        "local": {"models": ["model-a"]}
    }

    assert parse_strategy_score_weights({"profitability": "0.75"}) == {"profitability": 0.75}
    assert parse_strategy_score_weights('{"risk_control": 0.25}') == {"risk_control": 0.25}


@pytest.mark.parametrize(
    ("parse_value", "value", "message"),
    [
        (parse_ai_providers, "", "AI_PROVIDERS cannot be empty"),
        (parse_ai_providers, "{", "AI_PROVIDERS must be valid JSON"),
        (parse_ai_providers, "[]", "AI_PROVIDERS must decode to an object"),
        (parse_ai_providers, None, "AI_PROVIDERS cannot be null"),
        (parse_ai_providers, 1, "AI_PROVIDERS must be a dict or JSON string"),
        (parse_strategy_score_weights, "", "STRATEGY_SCORE_WEIGHTS cannot be empty"),
        (parse_strategy_score_weights, "{", "STRATEGY_SCORE_WEIGHTS must be valid JSON"),
        (
            parse_strategy_score_weights,
            "[]",
            "STRATEGY_SCORE_WEIGHTS must decode to an object",
        ),
        (parse_strategy_score_weights, None, "STRATEGY_SCORE_WEIGHTS cannot be null"),
        (
            parse_strategy_score_weights,
            1,
            "STRATEGY_SCORE_WEIGHTS must be a dict or JSON string",
        ),
        (
            parse_strategy_score_weights,
            {"profitability": "not-a-number"},
            "could not convert string to float: 'not-a-number'",
        ),
    ],
)
def test_json_settings_parsers_preserve_failure_messages(
    parse_value: Callable[[object], object],
    value: object,
    message: str,
) -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_value(value)

    assert str(exc_info.value) == message


def test_json_settings_validators_keep_environment_value_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_PROVIDERS", json.dumps({"environment": {"models": ["model-b"]}}))
    monkeypatch.setenv("STRATEGY_SCORE_WEIGHTS", json.dumps({"profitability": 0.6}))

    settings = Settings(_env_file=None)

    assert settings.AI_PROVIDERS == {"environment": {"models": ["model-b"]}}
    assert settings.STRATEGY_SCORE_WEIGHTS == {"profitability": 0.6}
