"""Persisted, revalidated provenance for OpenData-backed stock-daily reports.

A stock-analysis report may cite OpenData stock-daily evidence only when the
exact pinned publication and the authorization decision that allowed reading it
are persisted together and are still current immediately before the report row
is written. This module defines that immutable record (``StockDailyReportEvidence``
and its ``StockDailyReportEvidenceVector``), its strict JSON round-trip, and the
default-off gate that re-runs ``StockDailySnapshotAuthorizationAdapter.revalidate``
at report-save time.

The vector records the publication facts (dataset, source, instrument, market,
publication ID and sequence, content and contract hashes, capture/observation
times) plus the receipt basis (principal, entitlement revision, user/source
grant IDs and revisions, validity, purpose). Authorization is not inferred from
the vector: the gate reloads every current grant row through the adapter and
compares the receipt before allowing persistence.

Callers with no OpenData stock-daily provenance never enter this module, so the
legacy report path is unchanged. Nothing here performs network I/O or invents a
publication; tests use synthetic snapshots and grants.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, TypeGuard

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_analysis import JSONMapping, JSONValue
from app.services.stock_analysis.opendata_snapshot_authorization import (
    RECEIPT_VERSION,
    RESEARCH_PURPOSE,
    StockAnalysisSnapshotAuthorizationReceipt,
    StockAnalysisSnapshotScope,
)
from app.services.stock_analysis.stock_daily_snapshot_authorization_adapter import (
    DATASET_ID,
    SOURCE_ID,
    StockDailySnapshotAuthorizationAdapter,
    StockDailySnapshotAuthorizationError,
)

STOCK_DAILY_REPORT_EVIDENCE_VERSION: Final = "stock-analysis-report-evidence-v1"

_UTC = timezone.utc
_INSTRUMENT_ID = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z", re.ASCII)
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)

_EVIDENCE_KEYS = frozenset(
    {
        "dataset_id",
        "source_id",
        "instrument_id",
        "market",
        "publication_id",
        "publication_sequence",
        "content_sha256",
        "contract_sha256",
        "captured_at",
        "observed_at",
        "principal_user_id",
        "entitlement_revision",
        "user_grant_id",
        "user_grant_revision",
        "user_grant_valid_from",
        "user_grant_expires_at",
        "source_grant_id",
        "source_grant_revision",
        "source_grant_valid_from",
        "source_grant_expires_at",
        "authorized_at",
        "expires_at",
        "purpose",
        "authorization_receipt",
    }
)
_VECTOR_KEYS = frozenset({"version", "entries"})
_RECEIPT_KEYS = frozenset(
    {
        "receipt_version",
        "scope_sha256",
        "principal_user_id",
        "entitlement_revision",
        "user_grant_id",
        "user_grant_revision",
        "user_grant_revocation_revision",
        "user_grant_valid_from",
        "user_grant_expires_at",
        "source_grant_id",
        "source_grant_revision",
        "source_grant_revocation_revision",
        "source_grant_valid_from",
        "source_grant_expires_at",
        "source_registry_revision",
        "authorized_at",
        "expires_at",
        "decision_sha256",
    }
)


class StockDailyReportEvidenceError(ValueError):
    """Stable fail-closed denial for persisted report evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def stock_daily_report_evidence_expectation(
    *,
    instrument_id: str,
    publication_id: str,
    publication_sequence: int,
    content_sha256: str,
    contract_sha256: str,
) -> StockDailyReportEvidenceExpectation:
    """Build the plain expectation for one declared stock-daily selection."""
    return StockDailyReportEvidenceExpectation(
        dataset_id=DATASET_ID,
        source_id=SOURCE_ID,
        instrument_id=instrument_id,
        market=instrument_id[-2:],
        publication_id=publication_id,
        publication_sequence=publication_sequence,
        content_sha256=content_sha256,
        contract_sha256=contract_sha256,
    )


@dataclass(frozen=True, slots=True)
class StockDailyReportEvidenceExpectation:
    """Caller-supplied pinned publication facts the vector must match.

    This is the plain declaration carried by a task (or produced from one
    authorized read). It contains no receipt and proves no authorization on its
    own; the gate compares it with the persisted vector before revalidating.
    """

    dataset_id: str
    source_id: str
    instrument_id: str
    market: str
    publication_id: str
    publication_sequence: int
    content_sha256: str
    contract_sha256: str

    def __post_init__(self) -> None:
        _validate_publication_basis(
            dataset_id=self.dataset_id,
            source_id=self.source_id,
            instrument_id=self.instrument_id,
            market=self.market,
            publication_id=self.publication_id,
            publication_sequence=self.publication_sequence,
            content_sha256=self.content_sha256,
            contract_sha256=self.contract_sha256,
        )

    @property
    def identity_key(self) -> tuple[str, str, str, str]:
        """Return the exact dataset/source/instrument/market identity key."""
        return (self.dataset_id, self.source_id, self.instrument_id, self.market)


@dataclass(frozen=True, slots=True)
class StockDailyReportEvidence:
    """One authorized stock-daily dataset read pinned to one publication."""

    dataset_id: str
    source_id: str
    instrument_id: str
    market: str
    publication_id: str
    publication_sequence: int
    content_sha256: str
    contract_sha256: str
    captured_at: datetime
    observed_at: datetime
    principal_user_id: str
    entitlement_revision: str
    user_grant_id: str
    user_grant_revision: int
    user_grant_valid_from: datetime
    user_grant_expires_at: datetime
    source_grant_id: str
    source_grant_revision: int
    source_grant_valid_from: datetime
    source_grant_expires_at: datetime
    authorized_at: datetime
    expires_at: datetime
    purpose: str
    authorization_receipt: StockAnalysisSnapshotAuthorizationReceipt

    def __post_init__(self) -> None:
        _validate_publication_basis(
            dataset_id=self.dataset_id,
            source_id=self.source_id,
            instrument_id=self.instrument_id,
            market=self.market,
            publication_id=self.publication_id,
            publication_sequence=self.publication_sequence,
            content_sha256=self.content_sha256,
            contract_sha256=self.contract_sha256,
        )
        captured_at = self.captured_at
        observed_at = self.observed_at
        user_valid_from = _require_utc(self.user_grant_valid_from)
        user_expires_at = _require_utc(self.user_grant_expires_at)
        source_valid_from = _require_utc(self.source_grant_valid_from)
        source_expires_at = _require_utc(self.source_grant_expires_at)
        authorized_at = _require_utc(self.authorized_at)
        expires_at = _require_utc(self.expires_at)
        if (
            not isinstance(captured_at, datetime)
            or captured_at.tzinfo is None
            or captured_at.utcoffset() is None
            or not isinstance(observed_at, datetime)
            or observed_at.tzinfo is None
            or observed_at.utcoffset() is None
        ):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        captured_at = captured_at.astimezone(_UTC)
        observed_at = observed_at.astimezone(_UTC)
        if self.purpose != RESEARCH_PURPOSE:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        if (
            user_valid_from >= user_expires_at
            or source_valid_from >= source_expires_at
            or authorized_at >= expires_at
            or authorized_at < max(user_valid_from, source_valid_from)
            or min(user_expires_at, source_expires_at) != expires_at
        ):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")

        receipt = self.authorization_receipt
        _validate_receipt(receipt)
        if (
            self.principal_user_id != receipt.principal_user_id
            or self.entitlement_revision != receipt.entitlement_revision
            or self.user_grant_id != receipt.user_grant_id
            or self.user_grant_revision != receipt.user_grant_revision
            or user_valid_from != receipt.user_grant_valid_from
            or user_expires_at != receipt.user_grant_expires_at
            or self.source_grant_id != receipt.source_grant_id
            or self.source_grant_revision != receipt.source_grant_revision
            or source_valid_from != receipt.source_grant_valid_from
            or source_expires_at != receipt.source_grant_expires_at
            or authorized_at != receipt.authorized_at
            or expires_at != receipt.expires_at
        ):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_receipt_mismatch")

        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "observed_at", observed_at)
        object.__setattr__(self, "user_grant_valid_from", user_valid_from)
        object.__setattr__(self, "user_grant_expires_at", user_expires_at)
        object.__setattr__(self, "source_grant_valid_from", source_valid_from)
        object.__setattr__(self, "source_grant_expires_at", source_expires_at)
        object.__setattr__(self, "authorized_at", authorized_at)
        object.__setattr__(self, "expires_at", expires_at)

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """Return the exact dataset/source/instrument/market identity key."""
        return (self.dataset_id, self.source_id, self.instrument_id, self.market)

    def to_scope(self, *, user_id: str) -> StockAnalysisSnapshotScope:
        """Rebuild the exact policy scope for adapter revalidation."""
        return StockAnalysisSnapshotScope(
            user_id=user_id,
            dataset_id=self.dataset_id,
            source_id=self.source_id,
            instrument_id=self.instrument_id,
            market=self.market,
            publication_id=self.publication_id,
            capture_id=self.content_sha256,
        )

    def to_json(self) -> JSONMapping:
        """Return the complete record as strict JSON-compatible data."""
        return {
            "dataset_id": self.dataset_id,
            "source_id": self.source_id,
            "instrument_id": self.instrument_id,
            "market": self.market,
            "publication_id": self.publication_id,
            "publication_sequence": self.publication_sequence,
            "content_sha256": self.content_sha256,
            "contract_sha256": self.contract_sha256,
            "captured_at": self.captured_at.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "principal_user_id": self.principal_user_id,
            "entitlement_revision": self.entitlement_revision,
            "user_grant_id": self.user_grant_id,
            "user_grant_revision": self.user_grant_revision,
            "user_grant_valid_from": self.user_grant_valid_from.isoformat(),
            "user_grant_expires_at": self.user_grant_expires_at.isoformat(),
            "source_grant_id": self.source_grant_id,
            "source_grant_revision": self.source_grant_revision,
            "source_grant_valid_from": self.source_grant_valid_from.isoformat(),
            "source_grant_expires_at": self.source_grant_expires_at.isoformat(),
            "authorized_at": self.authorized_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "purpose": self.purpose,
            "authorization_receipt": _receipt_to_json(self.authorization_receipt),
        }

    @classmethod
    def from_json(cls, payload: object) -> StockDailyReportEvidence:
        """Parse and strictly validate one persisted evidence entry."""
        if not isinstance(payload, Mapping):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        if "publication_id" not in payload or not payload.get("publication_id"):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_publication_missing")
        if set(payload) != _EVIDENCE_KEYS:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        return cls(
            dataset_id=_text_field(payload["dataset_id"], maximum=128),
            source_id=_text_field(payload["source_id"], maximum=128),
            instrument_id=_instrument_field(payload["instrument_id"]),
            market=_text_field(payload["market"], maximum=8),
            publication_id=_publication_field(payload["publication_id"]),
            publication_sequence=_positive_int_field(payload["publication_sequence"]),
            content_sha256=_sha256_field(payload["content_sha256"]),
            contract_sha256=_sha256_field(payload["contract_sha256"]),
            captured_at=_parse_utc(payload["captured_at"]),
            observed_at=_parse_utc(payload["observed_at"]),
            principal_user_id=_text_field(payload["principal_user_id"], maximum=36),
            entitlement_revision=_revision_field(payload["entitlement_revision"]),
            user_grant_id=_text_field(payload["user_grant_id"], maximum=36),
            user_grant_revision=_positive_int_field(payload["user_grant_revision"]),
            user_grant_valid_from=_parse_utc(payload["user_grant_valid_from"]),
            user_grant_expires_at=_parse_utc(payload["user_grant_expires_at"]),
            source_grant_id=_text_field(payload["source_grant_id"], maximum=36),
            source_grant_revision=_positive_int_field(payload["source_grant_revision"]),
            source_grant_valid_from=_parse_utc(payload["source_grant_valid_from"]),
            source_grant_expires_at=_parse_utc(payload["source_grant_expires_at"]),
            authorized_at=_parse_utc(payload["authorized_at"]),
            expires_at=_parse_utc(payload["expires_at"]),
            purpose=_text_field(payload["purpose"], maximum=64),
            authorization_receipt=_receipt_from_json(payload["authorization_receipt"]),
        )


@dataclass(frozen=True, slots=True)
class StockDailyReportEvidenceVector:
    """One or more distinct dataset/instrument publications used by a report."""

    entries: tuple[StockDailyReportEvidence, ...]

    def __post_init__(self) -> None:
        if type(self.entries) is not tuple or not self.entries:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        identities: set[tuple[str, str, str, str]] = set()
        publications: set[tuple[str, str]] = set()
        for entry in self.entries:
            if not isinstance(entry, StockDailyReportEvidence):
                raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
            if entry.identity in identities:
                raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
            publication = (entry.dataset_id, entry.publication_id)
            if publication in publications:
                raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
            identities.add(entry.identity)
            publications.add(publication)

    def to_json(self) -> JSONMapping:
        """Return the versioned vector as strict JSON-compatible data."""
        entries: list[JSONValue] = [entry.to_json() for entry in self.entries]
        return {
            "version": STOCK_DAILY_REPORT_EVIDENCE_VERSION,
            "entries": entries,
        }

    @classmethod
    def from_json(cls, payload: object) -> StockDailyReportEvidenceVector:
        """Parse and strictly validate a persisted vector."""
        if not isinstance(payload, Mapping) or set(payload) != _VECTOR_KEYS:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        if payload["version"] != STOCK_DAILY_REPORT_EVIDENCE_VERSION:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        raw_entries = payload["entries"]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        entries = tuple(StockDailyReportEvidence.from_json(entry) for entry in raw_entries)
        return cls(entries=entries)

    def expectations(self) -> tuple[StockDailyReportEvidenceExpectation, ...]:
        """Return the plain publication facts declared by this vector."""
        return tuple(
            StockDailyReportEvidenceExpectation(
                dataset_id=entry.dataset_id,
                source_id=entry.source_id,
                instrument_id=entry.instrument_id,
                market=entry.market,
                publication_id=entry.publication_id,
                publication_sequence=entry.publication_sequence,
                content_sha256=entry.content_sha256,
                contract_sha256=entry.contract_sha256,
            )
            for entry in self.entries
        )

    def ensure_matches(
        self,
        expected: Sequence[StockDailyReportEvidenceExpectation],
    ) -> None:
        """Fail unless every vector entry exactly matches one expectation."""
        _match_expectations(self, expected)


class StockDailyReportEvidenceGate:
    """Revalidate persisted stock-daily evidence immediately before report save.

    The adapter is the only source of authorization truth. A missing vector is
    only allowed when the caller declares no expectation (legacy path); any
    declared OpenData provenance with a missing or changed vector fails closed.
    """

    def __init__(
        self,
        *,
        adapter: StockDailySnapshotAuthorizationAdapter | None = None,
    ) -> None:
        self._adapter = adapter or StockDailySnapshotAuthorizationAdapter()

    async def revalidate_for_report(
        self,
        *,
        session: AsyncSession,
        user_id: str,
        vector: StockDailyReportEvidenceVector | None,
        expected: Sequence[StockDailyReportEvidenceExpectation] | None,
    ) -> StockDailyReportEvidenceVector | None:
        """Return the vector only when it matches and is still authorized."""
        if vector is None and expected is None:
            return None
        if vector is None:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_missing")
        if not isinstance(vector, StockDailyReportEvidenceVector):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        if expected is None:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_expected_missing")
        if not _is_nonempty_text(user_id, maximum=36):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_principal_mismatch")
        _match_expectations(vector, expected)
        for entry in vector.entries:
            if entry.principal_user_id != user_id:
                raise StockDailyReportEvidenceError(
                    "stock_daily_report_evidence_principal_mismatch"
                )
            try:
                receipt = await self._adapter.revalidate(
                    session=session,
                    user_id=user_id,
                    scope=entry.to_scope(user_id=user_id),
                    receipt=entry.authorization_receipt,
                )
            except StockDailySnapshotAuthorizationError as exc:
                raise StockDailyReportEvidenceError(exc.code) from exc
            if receipt != entry.authorization_receipt:
                raise StockDailyReportEvidenceError("stock_daily_report_evidence_receipt_mismatch")
        return vector


def _validate_publication_basis(
    *,
    dataset_id: object,
    source_id: object,
    instrument_id: object,
    market: object,
    publication_id: object,
    publication_sequence: object,
    content_sha256: object,
    contract_sha256: object,
) -> None:
    """Validate the exact pinned publication identity shared by every record."""
    if dataset_id != DATASET_ID or source_id != SOURCE_ID:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if not isinstance(instrument_id, str) or _INSTRUMENT_ID.fullmatch(instrument_id) is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if market != instrument_id[-2:]:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if not isinstance(publication_id, str) or not publication_id:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_publication_missing")
    if _PUBLICATION_ID.fullmatch(publication_id) is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if type(publication_sequence) is not int or publication_sequence < 1:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if (
        not isinstance(content_sha256, str)
        or _SHA256.fullmatch(content_sha256) is None
        or not isinstance(contract_sha256, str)
        or _SHA256.fullmatch(contract_sha256) is None
    ):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")


def _validate_receipt(receipt: object) -> None:
    """Validate the receipt shape that is duplicated into the vector basis."""
    if not isinstance(receipt, StockAnalysisSnapshotAuthorizationReceipt):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_receipt_mismatch")
    if (
        receipt.receipt_version != RECEIPT_VERSION
        or not _is_sha256(receipt.scope_sha256)
        or not _is_sha256(receipt.decision_sha256)
        or not _is_nonempty_text(receipt.principal_user_id, maximum=36)
        or not _is_revision(receipt.entitlement_revision)
        or not _is_nonempty_text(receipt.user_grant_id, maximum=36)
        or not _is_positive_int(receipt.user_grant_revision)
        or not _is_positive_int(receipt.user_grant_revocation_revision)
        or not _is_nonempty_text(receipt.source_grant_id, maximum=36)
        or not _is_positive_int(receipt.source_grant_revision)
        or not _is_positive_int(receipt.source_grant_revocation_revision)
        or not _is_revision(receipt.source_registry_revision)
    ):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")


def _match_expectations(
    vector: StockDailyReportEvidenceVector,
    expected: Sequence[StockDailyReportEvidenceExpectation],
) -> None:
    """Require an exact one-to-one match between vector and expectations."""
    if isinstance(expected, (str, bytes)) or not isinstance(expected, Sequence):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    if not expected:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_expected_missing")
    by_identity: dict[tuple[str, str, str, str], StockDailyReportEvidenceExpectation] = {}
    for item in expected:
        if not isinstance(item, StockDailyReportEvidenceExpectation):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        if item.identity_key in by_identity:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
        by_identity[item.identity_key] = item
    if len(by_identity) != len(vector.entries):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_expected_mismatch")
    for entry in vector.entries:
        match = by_identity.get(entry.identity)
        if match is None:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_expected_mismatch")
        if not match.publication_id:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_publication_missing")
        if match.publication_id != entry.publication_id:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_publication_mismatch")
        if match.publication_sequence != entry.publication_sequence:
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_sequence_mismatch")
        if (
            match.content_sha256 != entry.content_sha256
            or match.contract_sha256 != entry.contract_sha256
        ):
            raise StockDailyReportEvidenceError("stock_daily_report_evidence_hash_mismatch")


def _receipt_to_json(
    receipt: StockAnalysisSnapshotAuthorizationReceipt,
) -> JSONMapping:
    return {
        "receipt_version": receipt.receipt_version,
        "scope_sha256": receipt.scope_sha256,
        "principal_user_id": receipt.principal_user_id,
        "entitlement_revision": receipt.entitlement_revision,
        "user_grant_id": receipt.user_grant_id,
        "user_grant_revision": receipt.user_grant_revision,
        "user_grant_revocation_revision": receipt.user_grant_revocation_revision,
        "user_grant_valid_from": receipt.user_grant_valid_from.isoformat(),
        "user_grant_expires_at": receipt.user_grant_expires_at.isoformat(),
        "source_grant_id": receipt.source_grant_id,
        "source_grant_revision": receipt.source_grant_revision,
        "source_grant_revocation_revision": receipt.source_grant_revocation_revision,
        "source_grant_valid_from": receipt.source_grant_valid_from.isoformat(),
        "source_grant_expires_at": receipt.source_grant_expires_at.isoformat(),
        "source_registry_revision": receipt.source_registry_revision,
        "authorized_at": receipt.authorized_at.isoformat(),
        "expires_at": receipt.expires_at.isoformat(),
        "decision_sha256": receipt.decision_sha256,
    }


def _receipt_from_json(payload: object) -> StockAnalysisSnapshotAuthorizationReceipt:
    if not isinstance(payload, Mapping) or set(payload) != _RECEIPT_KEYS:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    receipt = StockAnalysisSnapshotAuthorizationReceipt(
        receipt_version=_text_field(payload["receipt_version"], maximum=64),
        scope_sha256=_sha256_field(payload["scope_sha256"]),
        principal_user_id=_text_field(payload["principal_user_id"], maximum=36),
        entitlement_revision=_revision_field(payload["entitlement_revision"]),
        user_grant_id=_text_field(payload["user_grant_id"], maximum=36),
        user_grant_revision=_positive_int_field(payload["user_grant_revision"]),
        user_grant_revocation_revision=_positive_int_field(
            payload["user_grant_revocation_revision"]
        ),
        user_grant_valid_from=_parse_utc(payload["user_grant_valid_from"]),
        user_grant_expires_at=_parse_utc(payload["user_grant_expires_at"]),
        source_grant_id=_text_field(payload["source_grant_id"], maximum=36),
        source_grant_revision=_positive_int_field(payload["source_grant_revision"]),
        source_grant_revocation_revision=_positive_int_field(
            payload["source_grant_revocation_revision"]
        ),
        source_grant_valid_from=_parse_utc(payload["source_grant_valid_from"]),
        source_grant_expires_at=_parse_utc(payload["source_grant_expires_at"]),
        source_registry_revision=_revision_field(payload["source_registry_revision"]),
        authorized_at=_parse_utc(payload["authorized_at"]),
        expires_at=_parse_utc(payload["expires_at"]),
        decision_sha256=_sha256_field(payload["decision_sha256"]),
    )
    _validate_receipt(receipt)
    return receipt


def _text_field(value: object, *, maximum: int) -> str:
    if not _is_nonempty_text(value, maximum=maximum):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _instrument_field(value: object) -> str:
    if not isinstance(value, str) or _INSTRUMENT_ID.fullmatch(value) is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _publication_field(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_publication_missing")
    if _PUBLICATION_ID.fullmatch(value) is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _sha256_field(value: object) -> str:
    if not _is_sha256(value):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _revision_field(value: object) -> str:
    if not _is_revision(value):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _positive_int_field(value: object) -> int:
    if not _is_positive_int(value):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value


def _is_positive_int(value: object) -> TypeGuard[int]:
    return type(value) is int and value >= 1


def _is_nonempty_text(value: object, *, maximum: int) -> TypeGuard[str]:
    return isinstance(value, str) and 0 < len(value) <= maximum and value.strip() == value


def _is_sha256(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_revision(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _REVISION.fullmatch(value) is not None


def _require_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    return value.astimezone(_UTC)


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, TypeError, ValueError) as exc:
        raise StockDailyReportEvidenceError("stock_daily_report_evidence_invalid") from exc
    return _require_utc(parsed)


__all__ = [
    "DATASET_ID",
    "SOURCE_ID",
    "STOCK_DAILY_REPORT_EVIDENCE_VERSION",
    "StockDailyReportEvidence",
    "StockDailyReportEvidenceError",
    "StockDailyReportEvidenceExpectation",
    "StockDailyReportEvidenceGate",
    "StockDailyReportEvidenceVector",
    "stock_daily_report_evidence_expectation",
]
