from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.strategy import research as research_api
from app.config import get_settings
from app.db import database
from app.models.ai_research_v2 import ResearchDatasetSnapshot
from app.services.research.holdout_isolation import build_holdout_isolation_manifest
from app.services.research.holdout_sufficiency import (
    build_holdout_sufficiency,
    validate_holdout_sufficiency,
)
from tests.conftest import app


@pytest.fixture(autouse=True)
def enable_protocol_v2_writes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "AI_RESEARCH_PROTOCOL_V2_ENABLED", True)
    yield
    app.dependency_overrides.pop(research_api.get_dataset_object_resolver, None)


def _snapshot(
    *,
    partition_kind: str,
    symbol: str,
    start: str,
    end: str,
    object_id: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        partition_kind=partition_kind,
        instrument_manifest={"symbols": [symbol]},
        split_manifest={"start": start, "end": end},
        content_hash="a" * 64 if partition_kind == "DISCOVERY" else "b" * 64,
        snapshot_identity_hash="c" * 64 if partition_kind == "DISCOVERY" else "d" * 64,
        object_logical_id=object_id,
        object_version="v1",
        object_digest="e" * 64 if partition_kind == "DISCOVERY" else "f" * 64,
        point_in_time_cutoff=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _pair() -> tuple[SimpleNamespace, SimpleNamespace]:
    return (
        _snapshot(
            partition_kind="DISCOVERY",
            symbol="RB0",
            start="2022-01-01",
            end="2024-12-31",
            object_id="discovery-object",
        ),
        _snapshot(
            partition_kind="SEALED_HOLDOUT",
            symbol="HC0",
            start="2025-01-03",
            end="2025-12-31",
            object_id="sealed-object",
        ),
    )


def _build(discovery: SimpleNamespace, sealed: SimpleNamespace):
    return build_holdout_isolation_manifest(
        discovery=discovery,
        sealed=sealed,
        candidate_frozen_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def test_fully_isolated_snapshot_produces_deterministic_manifest() -> None:
    discovery, sealed = _pair()

    first = _build(discovery, sealed)
    second = _build(deepcopy(discovery), deepcopy(sealed))

    assert first == second
    assert len(first.manifest_hash) == 64
    assert first.discovery_universe == ("RB0",)
    assert first.sealed_universe == ("HC0",)
    assert first.label_mature_at == datetime(2025, 1, 2, tzinfo=timezone.utc)


def test_overlapping_universe_is_rejected() -> None:
    discovery, sealed = _pair()
    sealed.instrument_manifest = {"symbols": ["RB0"]}

    with pytest.raises(ValueError, match="HOLDOUT_ISOLATION_UNIVERSE_OVERLAP"):
        _build(discovery, sealed)


def test_overlapping_time_range_is_rejected() -> None:
    discovery, sealed = _pair()
    sealed.split_manifest["start"] = "2024-12-31"

    with pytest.raises(ValueError, match="HOLDOUT_ISOLATION_TIME_OVERLAP"):
        _build(discovery, sealed)


def test_reused_object_identity_is_rejected() -> None:
    discovery, sealed = _pair()
    sealed.object_logical_id = discovery.object_logical_id
    sealed.object_version = discovery.object_version
    sealed.object_digest = discovery.object_digest

    with pytest.raises(ValueError, match="HOLDOUT_ISOLATION_OBJECT_IDENTITY_REUSED"):
        _build(discovery, sealed)


def test_sealed_start_before_label_maturity_is_rejected() -> None:
    discovery, sealed = _pair()
    sealed.split_manifest["start"] = "2025-01-02"

    with pytest.raises(ValueError, match="HOLDOUT_SEALED_START_BEFORE_FREEZE_MATURITY"):
        _build(discovery, sealed)


@pytest.mark.parametrize("missing_field", ["symbols", "start", "object_logical_id"])
def test_missing_manifest_metadata_fails_closed(missing_field: str) -> None:
    discovery, sealed = _pair()
    if missing_field == "symbols":
        sealed.instrument_manifest = {}
    elif missing_field == "start":
        del sealed.split_manifest["start"]
    else:
        sealed.object_logical_id = None

    with pytest.raises(ValueError, match="HOLDOUT_ISOLATION_MANIFEST_REQUIRED"):
        _build(discovery, sealed)


def _sufficiency(**changes: object) -> dict[str, object]:
    proof = build_holdout_sufficiency(
        candidate_hash="2" * 64,
        policy_version="promotion-v1",
        artifact_hash="6" * 64,
    )
    proof.update(changes)
    if "evidence_digest" not in changes:
        proof = build_holdout_sufficiency(
            candidate_hash="2" * 64,
            policy_version="promotion-v1",
            artifact_hash="6" * 64,
            **dict(changes),
        )
    return proof


def _validate_sufficiency(proof: object) -> bool:
    return validate_holdout_sufficiency(
        proof,
        candidate_hash="2" * 64,
        policy_version="promotion-v1",
        artifact_hash="6" * 64,
    )


def test_sufficient_receipt_evidence_passes() -> None:
    assert _validate_sufficiency(_sufficiency()) is True


@pytest.mark.parametrize(
    "changes",
    [
        {"independent_samples": 2},
        {"valid_returns": 0},
        {"trial_count": 1},
        {"fold_count": 1},
        {"span_days": 30},
        {"label_mature": False},
    ],
)
def test_insufficient_receipt_evidence_is_rejected(changes: dict[str, object]) -> None:
    assert _validate_sufficiency(_sufficiency(**changes)) is False


def test_missing_sufficiency_evidence_fails_closed() -> None:
    with pytest.raises(ValueError, match="HOLDOUT_SUFFICIENCY_INVALID"):
        _validate_sufficiency({})


def test_sufficiency_evidence_digest_is_bound_to_artifact() -> None:
    proof = _sufficiency()
    proof["evidence_digest"] = "0" * 64

    with pytest.raises(ValueError, match="HOLDOUT_SUFFICIENCY_INVALID"):
        _validate_sufficiency(proof)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("defect", "reason_code"),
    [
        ("universe", "HOLDOUT_ISOLATION_UNIVERSE_OVERLAP"),
        ("time", "HOLDOUT_ISOLATION_TIME_OVERLAP"),
        ("object", "HOLDOUT_ISOLATION_OBJECT_IDENTITY_REUSED"),
        ("maturity", "HOLDOUT_SEALED_START_BEFORE_FREEZE_MATURITY"),
    ],
)
async def test_holdout_request_rejects_each_isolation_defect(
    client,
    auth_user,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    reason_code: str,
) -> None:
    from app.services.research import candidate_registry as candidate_registry_module
    from app.services.research import holdout_request as holdout_request_module
    from tests import test_ai_research_holdout_request as request_tests

    monkeypatch.setattr(
        holdout_request_module, "verify_candidate_integrity", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        candidate_registry_module, "verify_candidate_integrity", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        holdout_request_module, "require_verified_snapshot_integrity", lambda _snapshot: None
    )
    context, headers = await request_tests._request_context(
        auth_user, f"iteration207-isolation-{defect}"
    )
    sealed = context["sealed"]
    async with database.async_session_maker() as session:
        stored = await session.get(ResearchDatasetSnapshot, sealed.id)
        discovery = await session.get(
            ResearchDatasetSnapshot, context["candidate"].dataset_snapshot_id
        )
        if defect == "universe":
            stored.instrument_manifest = {"symbols": ["RB0"]}
        elif defect == "time":
            stored.split_manifest = {"start": "2023-01-01", "end": "2023-12-31"}
        elif defect == "object":
            stored.object_logical_id = discovery.object_logical_id
            stored.object_version = discovery.object_version
            stored.object_digest = discovery.object_digest
        else:
            stored.split_manifest = {"start": "2026-01-01", "end": "2026-12-31"}
            stored.point_in_time_cutoff = datetime(2027, 1, 1, tzinfo=timezone.utc)
        await session.commit()

    response = await client.post(
        request_tests._request_url(context),
        headers={**headers, "Idempotency-Key": f"iteration207-isolation-{defect}"},
        json=request_tests._request_payload(context),
    )

    assert response.status_code == 422
    assert response.json()["message"] == reason_code
