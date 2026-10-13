from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.schemas.ai_strategy_research import (
    AIStrategyResearchRunRequest,
    AIStrategyResearchTaskResponse,
)
from app.services.ai_strategy_research_task_lifecycle import (
    _find_trusted_task_snapshot_in_workspace,
)
from app.services.ai_strategy_research_task_manager import AIStrategyResearchTaskManager
from app.services.ai_strategy_research_task_projection import _redact_sensitive_values


def test_task_snapshot_lifecycle_rejects_unsigned_workspace_payload() -> None:
    raw_task = {
        "task_id": "untrusted-task",
        "status": "failed",
        "submitted_at": "2026-10-12T00:00:00+00:00",
        "research_workspace_id": "research-ws",
        "request_snapshot": {"prompt": "saved request"},
        "current_stage": "interrupted",
        "message": "legacy snapshot",
    }
    workspace = SimpleNamespace(
        id="research-ws",
        settings={"ai_research": {"tasks": [raw_task], "last_task": raw_task}},
    )

    recovered = _find_trusted_task_snapshot_in_workspace(
        workspace,
        user_id="user-1",
        task_id="untrusted-task",
    )

    assert recovered is None


@pytest.mark.asyncio
async def test_invalid_task_binding_preparation_fails_before_state_or_dispatch() -> None:
    class RecordingSnapshotStore:
        def __init__(self) -> None:
            self.saved: list[AIStrategyResearchTaskResponse] = []

        async def save_task(
            self,
            _user_id: str,
            response: AIStrategyResearchTaskResponse,
        ) -> None:
            self.saved.append(response)

    class RecordingResearchService:
        def __init__(self) -> None:
            self.requests: list[AIStrategyResearchRunRequest] = []

        async def run(
            self,
            _user_id: str,
            request: AIStrategyResearchRunRequest,
        ) -> None:
            self.requests.append(request)

    snapshot_store = RecordingSnapshotStore()
    research_service = RecordingResearchService()
    manager = AIStrategyResearchTaskManager(task_snapshot_store=snapshot_store)

    with pytest.raises(ValueError, match="AI_RESEARCH_REQUEST_PREPARATION_INVALID"):
        await manager.submit(
            "user-1",
            AIStrategyResearchRunRequest(prompt="research", symbol="000001.SZ"),
            service=research_service,
            request_preparer=lambda _task_id, request: {"prompt": request.prompt},
        )

    assert manager._tasks == {}
    assert snapshot_store.saved == []
    assert research_service.requests == []


def test_task_status_projection_redacts_nested_credentials() -> None:
    projected: Any = _redact_sensitive_values(
        {
            "gateway_config": {
                "endpoint": "paper.example",
                "params": {"api_key": "secret-key", "passphrase": "secret-passphrase"},
            },
            "observations": [{"token": "secret-token", "count": 2}],
        }
    )

    assert projected == {
        "gateway_config": {
            "endpoint": "paper.example",
            "params": {"api_key": "***", "passphrase": "***"},
        },
        "observations": [{"token": "***", "count": 2}],
    }
