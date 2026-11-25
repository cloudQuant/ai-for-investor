"""Pure authority and sealed-receipt verification helpers for research promotion."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from app.models.ai_research_v2 import (
    ResearchArtifact,
    ResearchArtifactContent,
    ResearchCandidate,
    ResearchEvaluation,
    ResearchExperimentEpoch,
    ResearchHoldoutAccessAudit,
    ResearchHoldoutArtifactBinding,
    ResearchHoldoutAuthorization,
    ResearchHoldoutEvaluationCommand,
    ResearchHoldoutExecution,
)
from app.services.research.canonical import canonical_json
from app.services.research.holdout_execution_contract import REQUIRED_HOLDOUT_GATE_CODES

_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SEALED_EVIDENCE_SCHEMA = "sealed-holdout-evidence-v1"
_SEALED_EVIDENCE_KIND = "sealed_holdout_evidence"
_SEALED_RECEIPT_KIND = "sealed_holdout_artifact_receipt"
_SEALED_RECEIPT_SCHEMA = "sealed-holdout-artifact-receipt-v1"
_SEALED_RECEIPT_MEDIA_TYPE = "application/vnd.ai-research.sealed-holdout-receipt+json"
_SEALED_RECEIPT_EXECUTOR = "sealed-evaluator-receipt-v1"
_HOLDOUT_BINDING_SCHEMA = "holdout-artifact-binding-v1"
_SEALED_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "authorization_id",
        "candidate_id",
        "candidate_hash",
        "experiment_epoch_id",
        "dataset_snapshot_id",
        "sealed_dataset_hash",
        "policy_version",
        "evaluator_identity",
        "evaluator_version",
        "measurements",
    }
)
_MEASUREMENT_KEYS = frozenset(
    {
        "returns",
        "trial_sharpes",
        "discovery_dataset_snapshot_hash",
        "cost_model_hash",
        "environment_hash",
        "capability_evidence_hash",
        "max_drawdown",
        "robustness_score",
        "cost_bps",
        "slippage_bps",
        "turnover",
        "capacity_notional",
        "extreme_path_loss",
        "execution_semantics_match",
        "security_critical_findings",
        "security_scan_hash",
    }
)


def utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize a naive or aware datetime to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _command_matches_candidate_and_authority(
    command: ResearchHoldoutEvaluationCommand,
    *,
    candidate: ResearchCandidate,
    evaluation: ResearchEvaluation,
    authority: Any,
    policy_version: str,
    started_at: datetime | None,
) -> bool:
    return (
        command.user_id == candidate.user_id
        and command.run_id == candidate.run_id
        and command.candidate_id == candidate.id == authority.candidate_id
        and command.candidate_hash == candidate.candidate_hash
        and command.expected_candidate_state == "FROZEN"
        and candidate.freeze_status == "FROZEN"
        and command.experiment_epoch_id == candidate.experiment_epoch_id
        and command.evaluation_id == evaluation.id == authority.evaluation_id
        and command.authorization_id == evaluation.authorization_id
        and command.policy_version == policy_version
        and command.stage == "HOLDOUT_PENDING"
        and command.lease_generation == authority.lease_generation
        and command.attempt_count == authority.lease_generation
        and started_at is not None
        and command.evaluator_identity == authority.evaluator_identity
        and command.evaluator_version == authority.evaluator_version
    )


def _authorization_matches_command(
    authorization: ResearchHoldoutAuthorization,
    *,
    command: ResearchHoldoutEvaluationCommand,
    lease_owner: str,
    lease_token_hash: str,
    started_at: datetime | None,
) -> bool:
    issued_at = utc_datetime(authorization.issued_at)
    consumed_at = utc_datetime(authorization.consumed_at)
    authorization_expiry = utc_datetime(authorization.expires_at)
    return (
        authorization.id == command.authorization_id
        and authorization.status == "CONSUMED"
        and authorization.experiment_epoch_id == command.experiment_epoch_id
        and authorization.candidate_id == command.candidate_id
        and authorization.candidate_hash == command.candidate_hash
        and authorization.dataset_snapshot_id == command.dataset_snapshot_id
        and authorization.policy_version == command.policy_version
        and authorization.evaluator_identity == command.evaluator_identity
        and authorization.capability_profile_id == command.capability_profile_id
        and authorization.capability_profile_version == command.capability_profile_version
        and authorization.capability_evidence_hash == command.capability_evidence_hash
        and authorization.issued_by == lease_owner
        and bool(_SHA256_HEX.fullmatch(authorization.token_hash))
        and authorization.token_hash != lease_token_hash
        and issued_at == started_at
        and consumed_at == started_at
        and authorization_expiry is not None
        and started_at is not None
        and authorization_expiry > started_at
    )


def _binding_and_eval_match(
    binding: ResearchHoldoutArtifactBinding,
    *,
    command: ResearchHoldoutEvaluationCommand,
    evaluation: ResearchEvaluation,
    claim_audit_id: str,
    authority: Any,
    expected_binding_hash: str,
    binding_expiry: datetime | None,
    started_at: datetime | None,
) -> bool:
    binding_ok = (
        binding.command_id == command.id
        and binding.user_id == command.user_id
        and binding.run_id == command.run_id
        and binding.authorization_id == command.authorization_id
        and binding.evaluation_id == evaluation.id
        and binding.experiment_epoch_id == command.experiment_epoch_id
        and binding.candidate_id == command.candidate_id
        and binding.dataset_snapshot_id == command.dataset_snapshot_id
        and binding.artifact_id == evaluation.returns_artifact_id
        and binding.claim_access_audit_id == claim_audit_id
        and binding.request_hash == command.request_hash
        and binding.lease_generation == authority.lease_generation
        and binding.binding_schema_version == _HOLDOUT_BINDING_SCHEMA
        and binding.authority_binding_hash == expected_binding_hash
        and binding_expiry is not None
    )
    eval_ok = (
        evaluation.experiment_epoch_id == command.experiment_epoch_id
        and evaluation.candidate_id == command.candidate_id
        and evaluation.dataset_snapshot_id == command.dataset_snapshot_id
        and evaluation.evaluation_type == "SEALED_HOLDOUT"
        and evaluation.evaluator_identity == authority.evaluator_identity
        and evaluation.evaluator_version == authority.evaluator_version
        and evaluation.policy_version == command.policy_version
        and evaluation.returns_artifact_id == binding.artifact_id
        and (evaluation.metrics or {}) == {}
        and (evaluation.gate_inputs or {}) == {}
        and evaluation.status == "RUNNING"
        and utc_datetime(evaluation.started_at) == started_at
        and evaluation.completed_at is None
    )
    return binding_ok and eval_ok


def _audit_matches_command(
    audit: ResearchHoldoutAccessAudit,
    *,
    action: str,
    reason_code: str,
    actor_identity: str,
    command: ResearchHoldoutEvaluationCommand,
    authorization_id: str,
    evaluation_id: str,
    lease_generation: int,
    expected_created_at: datetime | None,
) -> bool:
    return (
        audit.action == action
        and audit.result == "ACCEPTED"
        and audit.reason_code == reason_code
        and audit.actor_identity == actor_identity
        and audit.evaluator_version == command.evaluator_version
        and audit.requested_command_id == command.id
        and audit.command_id == command.id
        and audit.authorization_id == authorization_id
        and audit.evaluation_id == evaluation_id
        and audit.experiment_epoch_id == command.experiment_epoch_id
        and audit.candidate_id == command.candidate_id
        and audit.dataset_snapshot_id == command.dataset_snapshot_id
        and audit.lease_generation == lease_generation
        and audit.trace_id == command.trace_id
        and utc_datetime(audit.created_at) == expected_created_at
    )


def _artifact_and_payload_match(
    artifact: ResearchArtifact,
    *,
    retained: ResearchArtifactContent,
    decoded: Mapping[str, Any],
    expected_payload: Mapping[str, Any],
    digest: str,
    content: bytes,
    command: ResearchHoldoutEvaluationCommand,
    binding_created_at: datetime | None,
) -> bool:
    measurements = decoded.get("measurements")
    return (
        artifact.kind == _SEALED_EVIDENCE_KIND
        and artifact.content_hash == digest
        and artifact.size_bytes == len(content)
        and artifact.media_type == "application/json"
        and artifact.schema_version == _SEALED_EVIDENCE_SCHEMA
        and artifact.producer_identity == command.evaluator_identity
        and artifact.container_image_digest == command.evaluator_version
        and artifact.storage_uri == f"controlled://sealed-holdout-evidence/{digest}"
        and retained.artifact_id == artifact.id
        and utc_datetime(artifact.created_at) == binding_created_at
        and utc_datetime(retained.created_at) == binding_created_at
        and isinstance(measurements, dict)
        and set(decoded) == _SEALED_PAYLOAD_KEYS
        and set(measurements).issubset(_MEASUREMENT_KEYS)
        and decoded == expected_payload
        and canonical_json(decoded).encode("utf-8") == content
    )


def validate_command_promotion_base(
    *,
    command: ResearchHoldoutEvaluationCommand,
    candidate: ResearchCandidate,
    evaluation: ResearchEvaluation,
    authorization: ResearchHoldoutAuthorization,
    binding: ResearchHoldoutArtifactBinding,
    epoch: ResearchExperimentEpoch,
    claim_audit: ResearchHoldoutAccessAudit,
    checkpoint_audit: ResearchHoldoutAccessAudit,
    artifact: ResearchArtifact,
    retained: ResearchArtifactContent,
    authority: Any,
    policy_version: str,
    expected_binding_hash: str,
    binding_expiry: datetime | None,
    checkpoint_actor: str,
    decoded: Mapping[str, Any],
    expected_payload: Mapping[str, Any],
    digest: str,
    content: bytes,
) -> bool:
    """Verify command, authorization, binding, epoch, audits, and sealed evidence."""
    started_at = utc_datetime(command.started_at)
    disclosed_at = utc_datetime(epoch.disclosed_at)
    binding_created_at = utc_datetime(binding.created_at)
    epoch_ok = (
        epoch.status == "DISCLOSED"
        and epoch.selected_candidate_id == command.candidate_id
        and disclosed_at == started_at
        and epoch.closed_at is None
    )
    return (
        _command_matches_candidate_and_authority(
            command,
            candidate=candidate,
            evaluation=evaluation,
            authority=authority,
            policy_version=policy_version,
            started_at=started_at,
        )
        and _authorization_matches_command(
            authorization,
            command=command,
            lease_owner=binding.lease_owner,
            lease_token_hash=authority.lease_token_hash,
            started_at=started_at,
        )
        and _binding_and_eval_match(
            binding,
            command=command,
            evaluation=evaluation,
            claim_audit_id=claim_audit.id,
            authority=authority,
            expected_binding_hash=expected_binding_hash,
            binding_expiry=binding_expiry,
            started_at=started_at,
        )
        and epoch_ok
        and _audit_matches_command(
            claim_audit,
            action="CLAIM_STARTED",
            reason_code="HOLDOUT_CLAIM_STARTED",
            actor_identity=binding.lease_owner,
            command=command,
            authorization_id=authorization.id,
            evaluation_id=evaluation.id,
            lease_generation=authority.lease_generation,
            expected_created_at=started_at,
        )
        and _audit_matches_command(
            checkpoint_audit,
            action="CHECKPOINT_RECORDED",
            reason_code="HOLDOUT_FINALIZE_CHECKPOINT_RECORDED",
            actor_identity=checkpoint_actor,
            command=command,
            authorization_id=authorization.id,
            evaluation_id=evaluation.id,
            lease_generation=authority.lease_generation,
            expected_created_at=binding_created_at,
        )
        and _artifact_and_payload_match(
            artifact,
            retained=retained,
            decoded=decoded,
            expected_payload=expected_payload,
            digest=digest,
            content=content,
            command=command,
            binding_created_at=binding_created_at,
        )
    )


def _receipt_command_and_eval_match(
    command: ResearchHoldoutEvaluationCommand,
    *,
    candidate: ResearchCandidate,
    evaluation: ResearchEvaluation,
    authorization: ResearchHoldoutAuthorization,
    artifact: ResearchArtifact,
    epoch: ResearchExperimentEpoch,
    policy_version: str,
    receipt_fingerprint: str,
) -> bool:
    started_at = utc_datetime(command.started_at)
    completed_at = utc_datetime(evaluation.completed_at)
    command_ok = (
        command.status == "SUCCEEDED"
        and command.stage == "HOLDOUT_PENDING"
        and command.error_code is None
        and all(
            value is None
            for value in (
                command.lease_owner,
                command.lease_token_hash,
                command.lease_expires_at,
                command.lease_heartbeat_at,
            )
        )
        and command.candidate_id == candidate.id
        and command.candidate_hash == candidate.candidate_hash
        and command.freeze_receipt_fingerprint == receipt_fingerprint
        and command.policy_version == policy_version
        and candidate.freeze_status == "FROZEN"
    )
    eval_epoch_ok = (
        evaluation.candidate_id == candidate.id
        and evaluation.authorization_id == authorization.id
        and evaluation.experiment_epoch_id == command.experiment_epoch_id
        and evaluation.dataset_snapshot_id == command.dataset_snapshot_id
        and evaluation.evaluator_identity == command.evaluator_identity
        and evaluation.evaluator_version == command.evaluator_version
        and evaluation.policy_version == policy_version
        and evaluation.evaluation_type == "SEALED_HOLDOUT"
        and evaluation.returns_artifact_id == artifact.id
        and evaluation.status in {"PASSED", "REJECTED"}
        and started_at is not None
        and completed_at is not None
        and epoch.status == "CLOSED"
        and epoch.selected_candidate_id == candidate.id
        and utc_datetime(epoch.closed_at) == completed_at
    )
    return command_ok and eval_epoch_ok


def _receipt_auth_binding_and_audits_match(
    authorization: ResearchHoldoutAuthorization,
    *,
    command: ResearchHoldoutEvaluationCommand,
    candidate_id: str,
    evaluation_id: str,
    artifact_id: str,
    binding: ResearchHoldoutArtifactBinding,
    claim_audit: ResearchHoldoutAccessAudit,
    checkpoint_audit: ResearchHoldoutAccessAudit,
    checkpoint_actor: str,
    policy_version: str,
    expected_binding_hash: str,
) -> bool:
    auth_ok = (
        authorization.status == "CONSUMED"
        and authorization.experiment_epoch_id == command.experiment_epoch_id
        and authorization.candidate_id == candidate_id
        and authorization.candidate_hash == command.candidate_hash
        and authorization.dataset_snapshot_id == command.dataset_snapshot_id
        and authorization.policy_version == policy_version
        and authorization.evaluator_identity == command.evaluator_identity
        and authorization.capability_profile_id == command.capability_profile_id
        and authorization.capability_profile_version == command.capability_profile_version
        and authorization.capability_evidence_hash == command.capability_evidence_hash
        and authorization.issued_by == binding.lease_owner
    )
    audit_ok = (
        claim_audit.actor_identity == binding.lease_owner
        and claim_audit.result == "ACCEPTED"
        and claim_audit.reason_code == "HOLDOUT_CLAIM_STARTED"
        and claim_audit.evaluation_id == evaluation_id
        and claim_audit.authorization_id == authorization.id
        and checkpoint_audit.actor_identity == checkpoint_actor
        and checkpoint_audit.result == "ACCEPTED"
        and checkpoint_audit.reason_code == "HOLDOUT_FINALIZE_CHECKPOINT_RECORDED"
    )
    binding_ok = (
        binding.command_id == command.id
        and binding.authorization_id == authorization.id
        and binding.evaluation_id == evaluation_id
        and binding.artifact_id == artifact_id
        and binding.lease_owner == claim_audit.actor_identity
        and binding.lease_generation == command.lease_generation
        and binding.authority_binding_hash == expected_binding_hash
    )
    return auth_ok and audit_ok and binding_ok


def _receipt_execution_and_artifact_match(
    execution: ResearchHoldoutExecution,
    *,
    command: ResearchHoldoutEvaluationCommand,
    evaluation_id: str,
    binding_lease_owner: str,
    wire_command: Any,
    result: Any,
    artifact: ResearchArtifact,
    terminal: Mapping[str, Any],
    artifact_receipt: Mapping[str, Any],
    policy_version: str,
    policy_hash: str,
    input_evidence_hash: str,
) -> bool:
    state_ok = (execution.state == "OBSERVED" and execution.settled_at is None) or (
        execution.state == "SETTLED" and execution.settled_at is not None
    )
    exec_ok = (
        execution.command_id == command.id
        and execution.evaluation_id == evaluation_id
        and execution.lease_owner == binding_lease_owner
        and execution.lease_generation == command.lease_generation
        and execution.command_hash == wire_command.command_hash
        and execution.command_json == wire_command.snapshot
        and execution.state in {"OBSERVED", "SETTLED"}
        and execution.result_hash == sha256(result.payload).hexdigest()
        and execution.error_code is None
        and execution.observed_at is not None
        and state_ok
    )
    receipt_uri = f"controlled://sealed-holdout-artifact-receipt/{artifact_receipt['receipt_id']}"
    artifact_ok = (
        result.snapshot["status"] == "SUCCEEDED"
        and terminal["policy_version"] == policy_version
        and terminal["promotion_policy_hash"] == policy_hash
        and terminal["input_evidence_hash"] == input_evidence_hash
        and artifact_receipt["artifact_hash"] == artifact.content_hash
        and artifact_receipt["artifact_size_bytes"] == artifact.size_bytes
        and artifact.kind == _SEALED_RECEIPT_KIND
        and artifact.schema_version == _SEALED_RECEIPT_SCHEMA
        and artifact.media_type == _SEALED_RECEIPT_MEDIA_TYPE
        and artifact.producer_identity == command.evaluator_identity
        and artifact.container_image_digest == command.evaluator_version
        and artifact.storage_uri == receipt_uri
    )
    return exec_ok and artifact_ok


def validate_evaluator_receipt_chain(
    *,
    command: ResearchHoldoutEvaluationCommand,
    candidate: ResearchCandidate,
    evaluation: ResearchEvaluation,
    authorization: ResearchHoldoutAuthorization,
    artifact: ResearchArtifact,
    epoch: ResearchExperimentEpoch,
    binding: ResearchHoldoutArtifactBinding,
    execution: ResearchHoldoutExecution,
    claim_audit: ResearchHoldoutAccessAudit,
    checkpoint_audit: ResearchHoldoutAccessAudit,
    checkpoint_actor: str,
    wire_command: Any,
    result: Any,
    terminal: Mapping[str, Any],
    artifact_receipt: Mapping[str, Any],
    policy_version: str,
    policy_hash: str,
    receipt_fingerprint: str,
    input_evidence_hash: str,
    expected_binding_hash: str,
) -> bool:
    """Verify full database + wire receipt chain for sealed holdout results."""
    return (
        _receipt_command_and_eval_match(
            command,
            candidate=candidate,
            evaluation=evaluation,
            authorization=authorization,
            artifact=artifact,
            epoch=epoch,
            policy_version=policy_version,
            receipt_fingerprint=receipt_fingerprint,
        )
        and _receipt_auth_binding_and_audits_match(
            authorization,
            command=command,
            candidate_id=candidate.id,
            evaluation_id=evaluation.id,
            artifact_id=artifact.id,
            binding=binding,
            claim_audit=claim_audit,
            checkpoint_audit=checkpoint_audit,
            checkpoint_actor=checkpoint_actor,
            policy_version=policy_version,
            expected_binding_hash=expected_binding_hash,
        )
        and _receipt_execution_and_artifact_match(
            execution,
            command=command,
            evaluation_id=evaluation.id,
            binding_lease_owner=binding.lease_owner,
            wire_command=wire_command,
            result=result,
            artifact=artifact,
            terminal=terminal,
            artifact_receipt=artifact_receipt,
            policy_version=policy_version,
            policy_hash=policy_hash,
            input_evidence_hash=input_evidence_hash,
        )
    )


def validate_persisted_gate_decisions(
    *,
    outcomes: Sequence[Any],
    persisted: Iterable[Any],
    evaluation: ResearchEvaluation,
    command: ResearchHoldoutEvaluationCommand,
    input_evidence_hash: str,
    receipt_fingerprint: str,
    policy_hash: str,
    eligible: bool,
) -> bool:
    """Verify persisted gate decisions match the sealed receipt outcomes."""
    persisted_list = list(persisted)
    decisions = {decision.gate_code: decision for decision in persisted_list}
    if (
        len(outcomes) != len(REQUIRED_HOLDOUT_GATE_CODES)
        or tuple(outcome.code for outcome in outcomes) != REQUIRED_HOLDOUT_GATE_CODES
        or len(persisted_list) != len(REQUIRED_HOLDOUT_GATE_CODES)
        or set(decisions) != set(REQUIRED_HOLDOUT_GATE_CODES)
    ):
        return False
    for outcome in outcomes:
        decision = decisions[outcome.code]
        if (
            decision.evaluation_id != evaluation.id
            or decision.executor_version != _SEALED_RECEIPT_EXECUTOR
            or decision.status != outcome.status
            or decision.reason != outcome.reason
        ):
            return False
    expected_gate_inputs = {
        "input_evidence_hash": input_evidence_hash,
        "sealed_dataset_hash": command.sealed_dataset_hash,
        "strict_freeze_receipt_fingerprint": receipt_fingerprint,
        "promotion_policy_hash": policy_hash,
        "gate_statuses": {outcome.code: outcome.status for outcome in outcomes},
    }
    return (
        evaluation.status == ("PASSED" if eligible else "REJECTED")
        and dict(evaluation.metrics or {}) == {"promotion_eligible": eligible}
        and dict(evaluation.gate_inputs or {}) == expected_gate_inputs
    )
