"""Versioned, location-free sufficiency policy for external holdout receipts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.services.research.canonical import canonical_json

HOLDOUT_SUFFICIENCY_SCHEMA = "holdout-sufficiency-v1"
_SUFFICIENCY_KEYS = frozenset(
    {
        "schema_version",
        "policy_version",
        "candidate_hash",
        "strategy_family",
        "horizon_bars",
        "independent_samples",
        "valid_returns",
        "trial_count",
        "fold_count",
        "span_days",
        "label_mature",
        "evidence_digest",
    }
)


@dataclass(frozen=True, slots=True)
class SufficiencyPolicy:
    min_independent_samples: int
    min_valid_returns: int
    min_trials: int
    min_folds: int
    min_span_days: int


_POLICIES: dict[tuple[str, int], SufficiencyPolicy] = {
    ("intraday", 1): SufficiencyPolicy(252, 180, 5, 5, 60),
    ("daily", 1): SufficiencyPolicy(60, 40, 3, 3, 252),
    ("weekly", 1): SufficiencyPolicy(52, 36, 3, 3, 365),
}
_COUNT_FIELDS = (
    "independent_samples",
    "valid_returns",
    "trial_count",
    "fold_count",
    "span_days",
)


def validate_holdout_sufficiency(
    value: object,
    *,
    candidate_hash: str,
    policy_version: str,
    artifact_hash: str,
) -> bool:
    """Validate the proof binding and return whether server minima are met."""

    if not isinstance(value, Mapping) or set(value) != _SUFFICIENCY_KEYS:
        raise ValueError("HOLDOUT_SUFFICIENCY_INVALID")
    proof = dict(value)
    if (
        proof["schema_version"] != HOLDOUT_SUFFICIENCY_SCHEMA
        or proof["policy_version"] != policy_version
        or proof["candidate_hash"] != candidate_hash
        or type(proof["label_mature"]) is not bool
        or any(type(proof[field]) is not int or proof[field] < 0 for field in _COUNT_FIELDS)
    ):
        raise ValueError("HOLDOUT_SUFFICIENCY_INVALID")
    family = proof["strategy_family"]
    horizon = proof["horizon_bars"]
    if not isinstance(family, str) or type(horizon) is not int:
        raise ValueError("HOLDOUT_SUFFICIENCY_INVALID")
    policy = _POLICIES.get((family, horizon))
    if policy is None:
        raise ValueError("HOLDOUT_SUFFICIENCY_POLICY_UNSUPPORTED")

    digest = proof.pop("evidence_digest")
    expected_digest = sha256(
        canonical_json({**proof, "artifact_hash": artifact_hash}).encode("utf-8")
    ).hexdigest()
    if digest != expected_digest:
        raise ValueError("HOLDOUT_SUFFICIENCY_INVALID")
    return (
        proof["independent_samples"] >= policy.min_independent_samples
        and proof["valid_returns"] >= policy.min_valid_returns
        and proof["trial_count"] >= policy.min_trials
        and proof["fold_count"] >= policy.min_folds
        and proof["span_days"] >= policy.min_span_days
        and proof["label_mature"]
    )


def build_holdout_sufficiency(
    *,
    candidate_hash: str,
    policy_version: str,
    artifact_hash: str,
    strategy_family: str = "daily",
    horizon_bars: int = 1,
    independent_samples: int = 60,
    valid_returns: int = 40,
    trial_count: int = 3,
    fold_count: int = 3,
    span_days: int = 252,
    label_mature: bool = True,
) -> dict[str, Any]:
    """Build the canonical proof used by evaluator-side receipt producers."""

    proof: dict[str, Any] = {
        "schema_version": HOLDOUT_SUFFICIENCY_SCHEMA,
        "policy_version": policy_version,
        "candidate_hash": candidate_hash,
        "strategy_family": strategy_family,
        "horizon_bars": horizon_bars,
        "independent_samples": independent_samples,
        "valid_returns": valid_returns,
        "trial_count": trial_count,
        "fold_count": fold_count,
        "span_days": span_days,
        "label_mature": label_mature,
    }
    proof["evidence_digest"] = sha256(
        canonical_json({**proof, "artifact_hash": artifact_hash}).encode("utf-8")
    ).hexdigest()
    validate_holdout_sufficiency(
        proof,
        candidate_hash=candidate_hash,
        policy_version=policy_version,
        artifact_hash=artifact_hash,
    )
    return proof
