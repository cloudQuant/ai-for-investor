"""Regression checks for the typed AI research service boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api.strategy.base import (
    _model_has_persisted_field,
    redact_ai_strategy_research_payload,
)
from app.models.ai_research import AIStrategyResearchVersion
from app.services.ai_chat_service import AIChatService
from app.services.ai_strategy_research_version_service import _gate_deltas


def test_gate_deltas_accepts_status_from_version_model_instance() -> None:
    left = AIStrategyResearchVersion(quality_gate_status="failed")
    right = AIStrategyResearchVersion(quality_gate_status="passed")

    result = _gate_deltas(
        [],
        [],
        left_status=left.quality_gate_status,
        right_status=right.quality_gate_status,
    )

    assert result["quality_gate_status"]["left"] == "failed"
    assert result["quality_gate_status"]["right"] == "passed"
    assert result["quality_gate_status"]["improved"] is True


def test_strategy_generation_uses_validator_implementation_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.research import robustness

    validator = Mock()
    monkeypatch.setattr(robustness, "_validate_strategy_code_draft", validator)
    code = "class Candidate:\n    value = 1"
    content = json.dumps(
        {
            "answer_markdown": "已生成策略草案",
            "strategy_draft": {
                "name": "候选策略",
                "description": "用于回归的草案",
                "code": code,
            },
        },
        ensure_ascii=False,
    )

    result = AIChatService._parse_strategy_generation(content)

    validator.assert_called_once_with(code)
    assert result["answer"] == "已生成策略草案"
    assert result["strategy_draft"]["code"] == code


def test_strategy_base_uses_real_redactor_and_fails_closed_on_bad_field_sets() -> None:
    assert _model_has_persisted_field(SimpleNamespace(model_fields_set={"prompt"}), "prompt")
    assert _model_has_persisted_field(
        SimpleNamespace(model_fields_set=None, __fields_set__={"workflow_mode"}),
        "workflow_mode",
    )
    assert not _model_has_persisted_field(SimpleNamespace(model_fields_set=[]), "prompt")
    assert not _model_has_persisted_field(object(), "prompt")

    redacted = redact_ai_strategy_research_payload({"handoff": {"api_key": "secret"}})

    assert redacted == {"handoff": {"api_key": "***"}}
