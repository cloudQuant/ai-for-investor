"""Pure policy for user-scoped reads of pinned OpenData research snapshots.

Scopes cover both financial-statement observations and the pinned stock-daily
time-series publication (``cn-equity-stock-daily`` / ``akshare.daily``). For a
time-series publication with no source-native capture, ``capture_id`` is the
publication's exact ``content_sha256``: a platform publication content digest,
not a source capture or an issuer signature. The authorized caller must pass
that digest explicitly and must not infer it from a fetched response.

This module evaluates evidence supplied by a persistence adapter. It does not
load grants, authenticate a database snapshot, or call OpenData. The adapter
must obtain every evidence object with current reads from the authoritative
database; a caller-created object is not an authorization proof. Do not
synthesize a per-user source grant from ``AssetDataSourceRegistry`` alone: that
registry has no user, dataset, instrument, or publication scope. This policy is
not connected to task creation, background reads, or report storage. Its
receipt digest is unkeyed; an untrusted persistence boundary must authenticate
the receipt with a server-side MAC or signature.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

READ_DATA_PERMISSION: Final = "data:read"
RESEARCH_PURPOSE: Final = "RESEARCH"
RECEIPT_VERSION: Final = "stock-analysis-opendata-access-v1"
_DATASET_SOURCE: Final = {
    "sina_fzb_report_observations": "sina-fzb",
    "sina_lrb_report_observations": "sina-lrb",
    "cn-equity-stock-daily": "akshare.daily",
}
_INSTRUMENT_ID = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z", re.ASCII)
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_CAPTURE_ID = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)


class StockAnalysisSnapshotAuthorizationError(ValueError):
    """Stable denial from the OpenData snapshot authorization policy."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StockAnalysisSnapshotScope:
    """Exact resource and purpose requested by one stock-analysis task."""

    user_id: str
    dataset_id: str
    source_id: str
    instrument_id: str
    market: str
    publication_id: str
    capture_id: str
    purpose: str = RESEARCH_PURPOSE


@dataclass(frozen=True, slots=True)
class CurrentPrincipalEvidence:
    """Current user and READ_DATA state loaded by a trusted persistence adapter."""

    user_id: str
    is_active: bool
    permissions: frozenset[str]
    entitlement_revision: str


@dataclass(frozen=True, slots=True)
class UserReadDataGrantEvidence:
    """One exact user grant for reading a pinned dataset/instrument snapshot."""

    grant_id: str
    revision: int
    revocation_revision: int
    permission: str
    user_id: str
    dataset_id: str
    instrument_id: str
    market: str
    publication_id: str
    capture_id: str
    purpose: str
    valid_from: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class SourceResearchGrantEvidence:
    """One exact user/source grant for the same pinned research snapshot."""

    grant_id: str
    revision: int
    revocation_revision: int
    source_registry_revision: str
    user_id: str
    source_id: str
    dataset_id: str
    instrument_id: str
    market: str
    publication_id: str
    capture_id: str
    purpose: str
    valid_from: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class CurrentSourceRegistryEvidence:
    """Current source-registry decision, independently loaded for this request.

    ``research_allowed`` must come from the current source-policy evaluation;
    the source grant's own claimed registry revision is not sufficient evidence.
    """

    principal_user_id: str
    entitlement_revision: str
    source_id: str
    dataset_id: str
    market: str
    purpose: str
    revision: str
    research_allowed: bool


@dataclass(frozen=True, slots=True)
class StockAnalysisSnapshotAuthorizationReceipt:
    """Non-secret decision receipt to pin at task creation and recheck later.

    The digest is unkeyed: it detects accidental mutation, not forgery. An
    untrusted persistence boundary must add a server-side MAC or signature.
    The receipt does not make caller-supplied evidence authoritative.
    """

    receipt_version: str
    scope_sha256: str
    principal_user_id: str
    entitlement_revision: str
    user_grant_id: str
    user_grant_revision: int
    user_grant_revocation_revision: int
    user_grant_valid_from: datetime
    user_grant_expires_at: datetime
    source_grant_id: str
    source_grant_revision: int
    source_grant_revocation_revision: int
    source_grant_valid_from: datetime
    source_grant_expires_at: datetime
    source_registry_revision: str
    authorized_at: datetime
    expires_at: datetime
    decision_sha256: str


def authorize_stock_analysis_snapshot(
    *,
    scope: StockAnalysisSnapshotScope,
    principal: CurrentPrincipalEvidence | None,
    user_grant: UserReadDataGrantEvidence | None,
    source_grant: SourceResearchGrantEvidence | None,
    source_registry: CurrentSourceRegistryEvidence | None,
    now: datetime,
) -> StockAnalysisSnapshotAuthorizationReceipt:
    """Allow only when both current grants exactly cover the selected snapshot.

    The caller must build ``principal``, ``user_grant``, and ``source_grant``
    from current authoritative rows. Missing evidence always denies.
    """
    at = _as_utc(now, code="authorization_clock_invalid")
    _validate_scope(scope)
    if principal is None or user_grant is None or source_grant is None:
        raise StockAnalysisSnapshotAuthorizationError("authorization_evidence_missing")
    if source_registry is None:
        raise StockAnalysisSnapshotAuthorizationError("source_registry_evidence_missing")
    _validate_principal(scope=scope, principal=principal)
    _validate_user_grant(scope=scope, grant=user_grant, at=at)
    _validate_source_grant(scope=scope, grant=source_grant, at=at)
    _validate_source_registry(
        scope=scope,
        principal=principal,
        grant=source_grant,
        registry=source_registry,
    )

    user_valid_from = _as_utc(user_grant.valid_from, code="user_grant_invalid")
    user_expires_at = _as_utc(user_grant.expires_at, code="user_grant_invalid")
    source_valid_from = _as_utc(source_grant.valid_from, code="source_grant_invalid")
    source_expires_at = _as_utc(source_grant.expires_at, code="source_grant_invalid")
    expiry = min(user_expires_at, source_expires_at)
    scope_digest = _scope_sha256(scope)
    receipt_fields = {
        "receipt_version": RECEIPT_VERSION,
        "scope_sha256": scope_digest,
        "principal_user_id": principal.user_id,
        "entitlement_revision": principal.entitlement_revision,
        "user_grant_id": user_grant.grant_id,
        "user_grant_revision": user_grant.revision,
        "user_grant_revocation_revision": user_grant.revocation_revision,
        "user_grant_valid_from": user_valid_from.isoformat(),
        "user_grant_expires_at": user_expires_at.isoformat(),
        "source_grant_id": source_grant.grant_id,
        "source_grant_revision": source_grant.revision,
        "source_grant_revocation_revision": source_grant.revocation_revision,
        "source_grant_valid_from": source_valid_from.isoformat(),
        "source_grant_expires_at": source_expires_at.isoformat(),
        "source_registry_revision": source_registry.revision,
        "authorized_at": at.isoformat(),
        "expires_at": expiry.isoformat(),
        "decision": "ALLOW",
    }
    return StockAnalysisSnapshotAuthorizationReceipt(
        receipt_version=RECEIPT_VERSION,
        scope_sha256=scope_digest,
        principal_user_id=principal.user_id,
        entitlement_revision=principal.entitlement_revision,
        user_grant_id=user_grant.grant_id,
        user_grant_revision=user_grant.revision,
        user_grant_revocation_revision=user_grant.revocation_revision,
        user_grant_valid_from=user_valid_from,
        user_grant_expires_at=user_expires_at,
        source_grant_id=source_grant.grant_id,
        source_grant_revision=source_grant.revision,
        source_grant_revocation_revision=source_grant.revocation_revision,
        source_grant_valid_from=source_valid_from,
        source_grant_expires_at=source_expires_at,
        source_registry_revision=source_registry.revision,
        authorized_at=at,
        expires_at=expiry,
        decision_sha256=_canonical_sha256(receipt_fields),
    )


def revalidate_stock_analysis_snapshot(
    *,
    scope: StockAnalysisSnapshotScope,
    receipt: StockAnalysisSnapshotAuthorizationReceipt | None,
    principal: CurrentPrincipalEvidence | None,
    user_grant: UserReadDataGrantEvidence | None,
    source_grant: SourceResearchGrantEvidence | None,
    source_registry: CurrentSourceRegistryEvidence | None,
    now: datetime,
) -> StockAnalysisSnapshotAuthorizationReceipt:
    """Recheck task authority before a remote read and before report persistence.

    Every grant and entitlement revision must still match the receipt issued at
    task creation. A newly issued or widened grant requires creating a new task.
    """
    at = _as_utc(now, code="authorization_clock_invalid")
    if receipt is None:
        raise StockAnalysisSnapshotAuthorizationError("authorization_receipt_missing")
    _validate_receipt_shape(receipt)
    authorized_at = _as_utc(receipt.authorized_at, code="authorization_receipt_invalid")
    if authorized_at > at:
        raise StockAnalysisSnapshotAuthorizationError("authorization_receipt_invalid")
    if receipt.scope_sha256 != _scope_sha256(scope):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_changed")
    if at >= _as_utc(receipt.expires_at, code="authorization_receipt_invalid"):
        raise StockAnalysisSnapshotAuthorizationError("authorization_expired")

    current = authorize_stock_analysis_snapshot(
        scope=scope,
        principal=principal,
        user_grant=user_grant,
        source_grant=source_grant,
        source_registry=source_registry,
        now=at,
    )
    if (
        current.principal_user_id != receipt.principal_user_id
        or current.entitlement_revision != receipt.entitlement_revision
        or current.user_grant_id != receipt.user_grant_id
        or current.user_grant_revision != receipt.user_grant_revision
        or current.user_grant_revocation_revision != receipt.user_grant_revocation_revision
        or current.user_grant_valid_from != receipt.user_grant_valid_from
        or current.user_grant_expires_at != receipt.user_grant_expires_at
        or current.source_grant_id != receipt.source_grant_id
        or current.source_grant_revision != receipt.source_grant_revision
        or current.source_grant_revocation_revision != receipt.source_grant_revocation_revision
        or current.source_grant_valid_from != receipt.source_grant_valid_from
        or current.source_grant_expires_at != receipt.source_grant_expires_at
        or current.source_registry_revision != receipt.source_registry_revision
        or current.expires_at != receipt.expires_at
    ):
        raise StockAnalysisSnapshotAuthorizationError("authorization_revision_changed")
    if current.scope_sha256 != receipt.scope_sha256:
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_changed")
    if not _receipt_digest_is_valid(receipt):
        raise StockAnalysisSnapshotAuthorizationError("authorization_receipt_invalid")
    return receipt


def _validate_scope(scope: StockAnalysisSnapshotScope) -> None:
    if not isinstance(scope, StockAnalysisSnapshotScope):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if not _is_nonempty_text(scope.user_id, maximum=36):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if not _is_nonempty_text(scope.dataset_id, maximum=128):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if not _is_nonempty_text(scope.source_id, maximum=128):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if _DATASET_SOURCE.get(scope.dataset_id) != scope.source_id:
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if (
        not isinstance(scope.instrument_id, str)
        or _INSTRUMENT_ID.fullmatch(scope.instrument_id) is None
    ):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if scope.market != scope.instrument_id[-2:]:
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if (
        not isinstance(scope.publication_id, str)
        or _PUBLICATION_ID.fullmatch(scope.publication_id) is None
    ):
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if not isinstance(scope.capture_id, str) or _CAPTURE_ID.fullmatch(scope.capture_id) is None:
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")
    if scope.purpose != RESEARCH_PURPOSE:
        raise StockAnalysisSnapshotAuthorizationError("authorization_scope_invalid")


def _validate_principal(
    *, scope: StockAnalysisSnapshotScope, principal: CurrentPrincipalEvidence
) -> None:
    if (
        not isinstance(principal, CurrentPrincipalEvidence)
        or not isinstance(principal.is_active, bool)
        or principal.user_id != scope.user_id
        or not principal.is_active
        or not isinstance(principal.permissions, frozenset)
        or any(not isinstance(permission, str) for permission in principal.permissions)
        or READ_DATA_PERMISSION not in principal.permissions
        or not _is_revision(principal.entitlement_revision)
    ):
        raise StockAnalysisSnapshotAuthorizationError("principal_read_data_denied")


def _validate_user_grant(
    *, scope: StockAnalysisSnapshotScope, grant: UserReadDataGrantEvidence, at: datetime
) -> None:
    if not isinstance(grant, UserReadDataGrantEvidence):
        raise StockAnalysisSnapshotAuthorizationError("user_grant_invalid")
    _validate_grant_common(grant=grant, at=at, code="user_grant_invalid")
    if grant.revoked_at is not None:
        raise StockAnalysisSnapshotAuthorizationError("user_grant_revoked")
    if grant.permission != READ_DATA_PERMISSION:
        raise StockAnalysisSnapshotAuthorizationError("user_grant_scope_mismatch")
    if not _grant_matches_scope(grant=grant, scope=scope):
        raise StockAnalysisSnapshotAuthorizationError("user_grant_scope_mismatch")


def _validate_source_grant(
    *, scope: StockAnalysisSnapshotScope, grant: SourceResearchGrantEvidence, at: datetime
) -> None:
    if not isinstance(grant, SourceResearchGrantEvidence):
        raise StockAnalysisSnapshotAuthorizationError("source_grant_invalid")
    _validate_grant_common(grant=grant, at=at, code="source_grant_invalid")
    if grant.revoked_at is not None:
        raise StockAnalysisSnapshotAuthorizationError("source_grant_revoked")
    if (
        grant.user_id != scope.user_id
        or grant.source_id != scope.source_id
        or grant.dataset_id != scope.dataset_id
        or grant.instrument_id != scope.instrument_id
        or grant.market != scope.market
        or grant.publication_id != scope.publication_id
        or grant.capture_id != scope.capture_id
        or grant.purpose != RESEARCH_PURPOSE
        or not _is_revision(grant.source_registry_revision)
    ):
        raise StockAnalysisSnapshotAuthorizationError("source_grant_scope_mismatch")


def _validate_source_registry(
    *,
    scope: StockAnalysisSnapshotScope,
    principal: CurrentPrincipalEvidence,
    grant: SourceResearchGrantEvidence,
    registry: CurrentSourceRegistryEvidence,
) -> None:
    if not isinstance(registry, CurrentSourceRegistryEvidence):
        raise StockAnalysisSnapshotAuthorizationError("source_registry_evidence_invalid")
    if (
        registry.principal_user_id != scope.user_id
        or registry.entitlement_revision != principal.entitlement_revision
        or registry.source_id != scope.source_id
        or registry.dataset_id != scope.dataset_id
        or registry.market != scope.market
        or registry.purpose != RESEARCH_PURPOSE
        or not _is_revision(registry.revision)
        or not isinstance(registry.research_allowed, bool)
    ):
        raise StockAnalysisSnapshotAuthorizationError("source_registry_scope_mismatch")
    if not registry.research_allowed:
        raise StockAnalysisSnapshotAuthorizationError("source_registry_research_denied")
    if registry.revision != grant.source_registry_revision:
        raise StockAnalysisSnapshotAuthorizationError("source_registry_revision_mismatch")


def _validate_grant_common(*, grant: object, at: datetime, code: str) -> None:
    grant_id = getattr(grant, "grant_id", None)
    revision = getattr(grant, "revision", None)
    revocation_revision = getattr(grant, "revocation_revision", None)
    valid_from = getattr(grant, "valid_from", None)
    expires_at = getattr(grant, "expires_at", None)
    if (
        not _is_nonempty_text(grant_id, maximum=36)
        or type(revision) is not int
        or revision < 1
        or type(revocation_revision) is not int
        or revocation_revision < 1
    ):
        raise StockAnalysisSnapshotAuthorizationError(code)
    starts = _as_utc(valid_from, code=code)
    expires = _as_utc(expires_at, code=code)
    if starts >= expires:
        raise StockAnalysisSnapshotAuthorizationError(code)
    if at < starts or at >= expires:
        raise StockAnalysisSnapshotAuthorizationError("authorization_expired")


def _grant_matches_scope(
    *, grant: UserReadDataGrantEvidence, scope: StockAnalysisSnapshotScope
) -> bool:
    return (
        grant.user_id == scope.user_id
        and grant.dataset_id == scope.dataset_id
        and grant.instrument_id == scope.instrument_id
        and grant.market == scope.market
        and grant.publication_id == scope.publication_id
        and grant.capture_id == scope.capture_id
        and grant.purpose == RESEARCH_PURPOSE
    )


def _validate_receipt_shape(receipt: StockAnalysisSnapshotAuthorizationReceipt) -> None:
    if (
        not isinstance(receipt, StockAnalysisSnapshotAuthorizationReceipt)
        or receipt.receipt_version != RECEIPT_VERSION
        or not _is_sha256(receipt.scope_sha256)
        or not _is_sha256(receipt.decision_sha256)
        or not _is_nonempty_text(receipt.principal_user_id, maximum=36)
        or not _is_revision(receipt.entitlement_revision)
        or not _is_nonempty_text(receipt.user_grant_id, maximum=36)
        or type(receipt.user_grant_revision) is not int
        or receipt.user_grant_revision < 1
        or type(receipt.user_grant_revocation_revision) is not int
        or receipt.user_grant_revocation_revision < 1
        or not _is_nonempty_text(receipt.source_grant_id, maximum=36)
        or type(receipt.source_grant_revision) is not int
        or receipt.source_grant_revision < 1
        or type(receipt.source_grant_revocation_revision) is not int
        or receipt.source_grant_revocation_revision < 1
        or not _is_revision(receipt.source_registry_revision)
    ):
        raise StockAnalysisSnapshotAuthorizationError("authorization_receipt_invalid")
    authorized_at = _as_utc(receipt.authorized_at, code="authorization_receipt_invalid")
    expires_at = _as_utc(receipt.expires_at, code="authorization_receipt_invalid")
    user_valid_from = _as_utc(receipt.user_grant_valid_from, code="authorization_receipt_invalid")
    user_expires_at = _as_utc(receipt.user_grant_expires_at, code="authorization_receipt_invalid")
    source_valid_from = _as_utc(
        receipt.source_grant_valid_from, code="authorization_receipt_invalid"
    )
    source_expires_at = _as_utc(
        receipt.source_grant_expires_at, code="authorization_receipt_invalid"
    )
    if (
        authorized_at >= expires_at
        or authorized_at < max(user_valid_from, source_valid_from)
        or user_valid_from >= user_expires_at
        or source_valid_from >= source_expires_at
        or min(user_expires_at, source_expires_at) != expires_at
    ):
        raise StockAnalysisSnapshotAuthorizationError("authorization_receipt_invalid")


def _receipt_digest_is_valid(receipt: StockAnalysisSnapshotAuthorizationReceipt) -> bool:
    authorized_at = _as_utc(receipt.authorized_at, code="authorization_receipt_invalid").isoformat()
    expires_at = _as_utc(receipt.expires_at, code="authorization_receipt_invalid").isoformat()
    user_valid_from = _as_utc(
        receipt.user_grant_valid_from, code="authorization_receipt_invalid"
    ).isoformat()
    user_expires_at = _as_utc(
        receipt.user_grant_expires_at, code="authorization_receipt_invalid"
    ).isoformat()
    source_valid_from = _as_utc(
        receipt.source_grant_valid_from, code="authorization_receipt_invalid"
    ).isoformat()
    source_expires_at = _as_utc(
        receipt.source_grant_expires_at, code="authorization_receipt_invalid"
    ).isoformat()
    payload = {
        "receipt_version": receipt.receipt_version,
        "scope_sha256": receipt.scope_sha256,
        "principal_user_id": receipt.principal_user_id,
        "entitlement_revision": receipt.entitlement_revision,
        "user_grant_id": receipt.user_grant_id,
        "user_grant_revision": receipt.user_grant_revision,
        "user_grant_revocation_revision": receipt.user_grant_revocation_revision,
        "user_grant_valid_from": user_valid_from,
        "user_grant_expires_at": user_expires_at,
        "source_grant_id": receipt.source_grant_id,
        "source_grant_revision": receipt.source_grant_revision,
        "source_grant_revocation_revision": receipt.source_grant_revocation_revision,
        "source_grant_valid_from": source_valid_from,
        "source_grant_expires_at": source_expires_at,
        "source_registry_revision": receipt.source_registry_revision,
        "authorized_at": authorized_at,
        "expires_at": expires_at,
        "decision": "ALLOW",
    }
    return _canonical_sha256(payload) == receipt.decision_sha256


def _scope_sha256(scope: StockAnalysisSnapshotScope) -> str:
    _validate_scope(scope)
    return _canonical_sha256(
        {
            "version": "stock-analysis-opendata-scope-v1",
            "user_id": scope.user_id,
            "dataset_id": scope.dataset_id,
            "source_id": scope.source_id,
            "instrument_id": scope.instrument_id,
            "market": scope.market,
            "publication_id": scope.publication_id,
            "capture_id": scope.capture_id,
            "purpose": scope.purpose,
        }
    )


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_utc(value: object, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StockAnalysisSnapshotAuthorizationError(code)
    return value.astimezone(timezone.utc)


def _is_nonempty_text(value: object, *, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and value.strip() == value


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value, re.ASCII) is not None


def _is_revision(value: object) -> bool:
    return isinstance(value, str) and _REVISION.fullmatch(value) is not None
