"""Explicit deterministic stage executors for the disabled protocol-v2 worker.

These executors are deliberately not an LLM, sandbox, evaluator, or backtest
implementation.  They will be extended only with durable, provenance-labelled
outputs; until then an explicitly enabled deployment fails closed rather than
inventing an AI-generated candidate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.research.artifact_broker import ArtifactBroker, StageOutputContext
from app.services.research.workflow_worker import StageExecutionContext, StageExecutionOutcome

_PRODUCER_IDENTITY = "protocol-v2-deterministic-template"
_SCHEMA_VERSION = "deterministic-stage-receipt-v1"


@dataclass(slots=True)
class _StageOutputContextAdapter:
    """Mutable adapter for the artifact broker's writable context protocol."""

    user_id: str
    run_id: str
    task_id: str
    stage_attempt_id: str
    lease_token: str
    stage: str
    request_hash: str


class DeterministicClarifyExecutor:
    """Reserve a named implementation boundary for server-side clarification."""

    async def execute(self, context: StageExecutionContext) -> StageExecutionOutcome:
        """Persist a bounded clarification receipt without calling a model."""

        if context.stage != "CLARIFY":
            return StageExecutionOutcome.failed("RESEARCH_DETERMINISTIC_STAGE_CONTEXT_INVALID")
        artifact = await _register_receipt(context)
        return StageExecutionOutcome.succeeded(
            next_stage="GENERATE",
            output_artifact_id=artifact.id,
        )


class DeterministicGenerateExecutor:
    """Reserve a named implementation boundary for deterministic generation."""

    async def execute(self, context: StageExecutionContext) -> StageExecutionOutcome:
        """Retain a no-model receipt while refusing to pretend it is a candidate."""

        if context.stage != "GENERATE":
            return StageExecutionOutcome.failed("RESEARCH_DETERMINISTIC_STAGE_CONTEXT_INVALID")
        artifact = await _register_receipt(context)
        return StageExecutionOutcome.failed(
            "RESEARCH_GENERATION_NOT_EXECUTED",
            output_artifact_id=artifact.id,
        )


async def _register_receipt(context: StageExecutionContext):
    """Write the one immutable stage output allowed for a leased attempt."""

    receipt = {
        "schema_version": _SCHEMA_VERSION,
        "stage": context.stage,
        "task_id": context.task_id,
        "run_id": context.run_id,
        "request_hash": context.request_hash,
        "trace_id": context.trace_id,
        "origin": "deterministic_template",
        "transformation_chain": ["receipt_persisted"],
        "fallback_chain": [
            "deterministic_factory_selected",
            "model_provider_not_invoked",
        ],
        "model_invocation_id": None,
        "model_call": "NOT_CALLED",
        "execution_state": "NOT_EXECUTED",
        "candidate_id": None,
        "sandbox_receipt_id": None,
        "evaluation_id": None,
        "notice": "No model, sandbox, backtest, evaluator, or market trial was executed.",
    }
    output_context: StageOutputContext = _StageOutputContextAdapter(
        user_id=context.user_id,
        run_id=context.run_id,
        task_id=context.task_id,
        stage_attempt_id=context.stage_attempt_id,
        lease_token=context.lease_token,
        stage=context.stage,
        request_hash=context.request_hash,
    )
    return await ArtifactBroker().register_stage_output(
        context=output_context,
        kind=f"deterministic_{context.stage.lower()}_receipt",
        content=json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        media_type="application/json",
        schema_version=_SCHEMA_VERSION,
        producer_identity=_PRODUCER_IDENTITY,
    )
