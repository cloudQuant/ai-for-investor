"""Pure parsers for JSON-valued application settings."""

import json
from typing import Any


def parse_ai_providers(value: object) -> dict[str, dict[str, Any]]:
    """Normalize AI provider settings supplied as a dictionary or JSON string."""
    if isinstance(value, dict):
        return {
            str(key): dict(provider)
            for key, provider in value.items()
            if isinstance(provider, dict)
        }
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("AI_PROVIDERS cannot be empty")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("AI_PROVIDERS must be valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("AI_PROVIDERS must decode to an object")
        return {
            str(key): dict(provider) for key, provider in data.items() if isinstance(provider, dict)
        }
    if value is None:
        raise ValueError("AI_PROVIDERS cannot be null")
    raise ValueError("AI_PROVIDERS must be a dict or JSON string")


def parse_strategy_score_weights(value: object) -> dict[str, float]:
    """Normalize strategy score weights supplied as a dictionary or JSON string."""
    if isinstance(value, dict):
        return {str(key): float(weight) for key, weight in value.items()}
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("STRATEGY_SCORE_WEIGHTS cannot be empty")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("STRATEGY_SCORE_WEIGHTS must be valid JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("STRATEGY_SCORE_WEIGHTS must decode to an object")
        return {str(key): float(weight) for key, weight in data.items()}
    if value is None:
        raise ValueError("STRATEGY_SCORE_WEIGHTS cannot be null")
    raise ValueError("STRATEGY_SCORE_WEIGHTS must be a dict or JSON string")
