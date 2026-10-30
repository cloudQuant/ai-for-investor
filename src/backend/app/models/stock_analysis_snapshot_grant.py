"""Persist exact user and source grants for OpenData stock snapshots.

These rows are an empty-by-default storage foundation. They do not issue
authority, authenticate the issuer, or make client-supplied ORM objects
authoritative. A trusted adapter must load current rows from the database,
require exactly one matching ``ISSUED`` audit and at most one later ``REVOKED``
audit, authenticate each actor as an active human with the dedicated grant
permission, check the principal's current ``data:read`` permission, and compare
the source grant's registry revision to an independently loaded current
registry decision. The schema and ORM events do not currently enforce that
complete audit or actor contract.

Grant scope is represented by scalar columns and treated as immutable. ORM
unit-of-work listeners validate inserts and reject ordinary object mutations,
while bulk ORM statements and direct SQL can bypass them. Revocation is a
separate audit event so a grant's scope and issue revision never change. The
database does not prove an ordered issue/revocation chain or authenticate a
human actor. Database-level UPDATE/DELETE protection is a separate deployment
control and is not provided here. SQLite does not preserve timezone metadata in
``DateTime`` values; ORM inserts normalize aware timestamps to UTC, and a
trusted adapter must restore UTC awareness after reading persisted values.

The audit table has scalar foreign-key columns rather than ORM relationship
attributes. When an issuer stages a grant and its audit event in one
transaction, it must flush the grant row before adding/flushing the audit row;
SQLAlchemy cannot infer the object dependency from scalar IDs alone. The
subject user must already be persisted before its grant is flushed. Keep both
flushes in the same transaction and commit once so an audit failure rolls back
the grant as well.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.db.database import Base

_PIT_DATETIME = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _exact_ascii_string(length: int) -> String:
    """Keep policy identifiers byte-exact and narrow on SQLite/MySQL/PostgreSQL."""
    return (
        String(length, collation="BINARY")
        .with_variant(
            mysql.VARCHAR(length, charset="ascii", collation="ascii_bin"),
            "mysql",
        )
        .with_variant(postgresql.VARCHAR(length, collation="C"), "postgresql")
    )


class ImmutableStockSnapshotGrantError(RuntimeError):
    """Raised when ORM code tries to mutate persisted grant or audit facts."""


class InvalidStockSnapshotGrantRecord(ValueError):
    """Raised when an ORM insert violates the exact snapshot storage contract."""


_DATASET_SOURCE = {
    "sina_fzb_report_observations": "sina-fzb",
    "sina_lrb_report_observations": "sina-lrb",
}
_INSTRUMENT_ID = re.compile(r"[0-9]{6}\.(?:SH|SZ)\Z", re.ASCII)
_PUBLICATION_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_CAPTURE_ID = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_POLICY_VERSION = "stock-analysis-opendata-access-v1"


class StockSnapshotUserReadGrant(Base):
    """One exact user permission to read one pinned stock-analysis snapshot.

    Revisions are new rows with new identifiers. There is no wildcard scope,
    implicit expiration, default grant, or mutable status field. A revoke is
    represented by a separate ``REVOKED`` audit row.
    """

    __tablename__ = "stock_snapshot_user_read_grants"
    __table_args__ = (
        CheckConstraint(
            "permission = 'data:read'",
            name="ck_stock_snapshot_user_permission",
        ),
        CheckConstraint(
            "dataset_id IN ('sina_fzb_report_observations', 'sina_lrb_report_observations')",
            name="ck_stock_snapshot_user_dataset",
        ),
        CheckConstraint(
            "market IN ('SH', 'SZ') AND length(instrument_id) = 9 "
            "AND substr(instrument_id, 8, 2) = market",
            name="ck_stock_snapshot_user_market",
        ),
        CheckConstraint(
            "length(publication_id) = 32 AND length(capture_id) = 64",
            name="ck_stock_snapshot_user_snapshot_ids",
        ),
        CheckConstraint(
            "purpose = 'RESEARCH'",
            name="ck_stock_snapshot_user_purpose",
        ),
        CheckConstraint("revision >= 1", name="ck_stock_snapshot_user_revision"),
        CheckConstraint(
            "expires_at > valid_from",
            name="ck_stock_snapshot_user_validity",
        ),
        UniqueConstraint(
            "user_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
            "purpose",
            "revision",
            name="uq_stock_snapshot_user_scope_revision",
        ),
        # The composite key lets audit rows bind both subject and grant revision.
        UniqueConstraint("id", "user_id", "revision", name="uq_stock_snapshot_user_audit_revision"),
        Index(
            "ix_stock_snapshot_user_lookup",
            "user_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        _exact_ascii_string(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_stock_snapshot_user_grant_user", ondelete="RESTRICT"),
        nullable=False,
    )
    permission: Mapped[str] = mapped_column(_exact_ascii_string(32), nullable=False)
    dataset_id: Mapped[str] = mapped_column(_exact_ascii_string(128), nullable=False)
    instrument_id: Mapped[str] = mapped_column(_exact_ascii_string(16), nullable=False)
    market: Mapped[str] = mapped_column(_exact_ascii_string(8), nullable=False)
    publication_id: Mapped[str] = mapped_column(_exact_ascii_string(32), nullable=False)
    capture_id: Mapped[str] = mapped_column(_exact_ascii_string(64), nullable=False)
    purpose: Mapped[str] = mapped_column(_exact_ascii_string(24), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(_PIT_DATETIME, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_PIT_DATETIME, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _PIT_DATETIME,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class StockSnapshotSourceResearchGrant(Base):
    """One exact user's research right for the same pinned source snapshot.

    ``source_registry_revision`` records the revision used at issue time. It
    never substitutes for an independent current-registry read by the trusted
    authorization adapter.
    """

    __tablename__ = "stock_snapshot_source_research_grants"
    __table_args__ = (
        CheckConstraint(
            "(dataset_id = 'sina_fzb_report_observations' AND source_id = 'sina-fzb') OR "
            "(dataset_id = 'sina_lrb_report_observations' AND source_id = 'sina-lrb')",
            name="ck_stock_snapshot_source_dataset",
        ),
        CheckConstraint(
            "market IN ('SH', 'SZ') AND length(instrument_id) = 9 "
            "AND substr(instrument_id, 8, 2) = market",
            name="ck_stock_snapshot_source_market",
        ),
        CheckConstraint(
            "length(publication_id) = 32 AND length(capture_id) = 64",
            name="ck_stock_snapshot_source_snapshot_ids",
        ),
        CheckConstraint(
            "purpose = 'RESEARCH'",
            name="ck_stock_snapshot_source_purpose",
        ),
        CheckConstraint("revision >= 1", name="ck_stock_snapshot_source_revision"),
        CheckConstraint(
            "length(source_registry_revision) BETWEEN 1 AND 128",
            name="ck_stock_snapshot_source_registry_revision",
        ),
        CheckConstraint(
            "expires_at > valid_from",
            name="ck_stock_snapshot_source_validity",
        ),
        UniqueConstraint(
            "user_id",
            "source_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
            "purpose",
            "revision",
            name="uq_stock_snapshot_source_scope_revision",
        ),
        UniqueConstraint(
            "id", "user_id", "revision", name="uq_stock_snapshot_source_audit_revision"
        ),
        Index(
            "ix_stock_snapshot_source_lookup",
            "user_id",
            "source_id",
            "dataset_id",
            "instrument_id",
            "publication_id",
            "capture_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        _exact_ascii_string(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", name="fk_stock_snapshot_source_grant_user", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[str] = mapped_column(_exact_ascii_string(128), nullable=False)
    dataset_id: Mapped[str] = mapped_column(_exact_ascii_string(128), nullable=False)
    instrument_id: Mapped[str] = mapped_column(_exact_ascii_string(16), nullable=False)
    market: Mapped[str] = mapped_column(_exact_ascii_string(8), nullable=False)
    publication_id: Mapped[str] = mapped_column(_exact_ascii_string(32), nullable=False)
    capture_id: Mapped[str] = mapped_column(_exact_ascii_string(64), nullable=False)
    purpose: Mapped[str] = mapped_column(_exact_ascii_string(24), nullable=False)
    source_registry_revision: Mapped[str] = mapped_column(_exact_ascii_string(128), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(_PIT_DATETIME, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_PIT_DATETIME, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        _PIT_DATETIME,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class StockSnapshotGrantAudit(Base):
    """Issue or revoke event for exactly one stored snapshot grant.

    The ``grant_revision`` matches the immutable grant row. Issuance records
    use ``revocation_revision=1``; the single revoke event uses revision 2. A
    new issuance is represented by another grant row and a new issuance
    event. Readers must select only the greatest scope revision and fail
    closed when that head is expired or revoked. ``idempotency_key_sha256`` is
    generated by a trusted server and is never accepted directly from an API
    client.
    """

    __tablename__ = "stock_snapshot_grant_audits"
    __table_args__ = (
        CheckConstraint(
            "(user_grant_id IS NOT NULL AND source_grant_id IS NULL) OR "
            "(user_grant_id IS NULL AND source_grant_id IS NOT NULL)",
            name="ck_stock_snapshot_audit_one_grant",
        ),
        CheckConstraint(
            "event_type IN ('ISSUED', 'REVOKED')",
            name="ck_stock_snapshot_audit_event",
        ),
        CheckConstraint(
            "grant_revision >= 1 AND "
            "((event_type = 'ISSUED' AND revocation_revision = 1) OR "
            "(event_type = 'REVOKED' AND revocation_revision = 2))",
            name="ck_stock_snapshot_audit_revision",
        ),
        CheckConstraint(
            f"policy_version = '{_POLICY_VERSION}'",
            name="ck_stock_snapshot_audit_policy",
        ),
        CheckConstraint(
            "length(reason_code) BETWEEN 1 AND 128",
            name="ck_stock_snapshot_audit_reason",
        ),
        CheckConstraint(
            "length(idempotency_key_sha256) = 64",
            name="ck_stock_snapshot_audit_idempotency_hash",
        ),
        ForeignKeyConstraint(
            ["user_grant_id", "subject_user_id", "grant_revision"],
            [
                "stock_snapshot_user_read_grants.id",
                "stock_snapshot_user_read_grants.user_id",
                "stock_snapshot_user_read_grants.revision",
            ],
            name="fk_stock_snapshot_audit_user_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_grant_id", "subject_user_id", "grant_revision"],
            [
                "stock_snapshot_source_research_grants.id",
                "stock_snapshot_source_research_grants.user_id",
                "stock_snapshot_source_research_grants.revision",
            ],
            name="fk_stock_snapshot_audit_source_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["subject_user_id"],
            ["users.id"],
            name="fk_stock_snapshot_audit_subject",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_stock_snapshot_audit_actor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "user_grant_id",
            "event_type",
            name="uq_stock_snapshot_audit_user_event",
        ),
        UniqueConstraint(
            "source_grant_id",
            "event_type",
            name="uq_stock_snapshot_audit_source_event",
        ),
        UniqueConstraint(
            "idempotency_key_sha256",
            name="uq_stock_snapshot_audit_idempotency",
        ),
        Index(
            "ix_stock_snapshot_audit_subject_time",
            "subject_user_id",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        _exact_ascii_string(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_grant_id: Mapped[str | None] = mapped_column(_exact_ascii_string(36), nullable=True)
    source_grant_id: Mapped[str | None] = mapped_column(_exact_ascii_string(36), nullable=True)
    subject_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(_exact_ascii_string(16), nullable=False)
    grant_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    revocation_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(_exact_ascii_string(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(_PIT_DATETIME, nullable=False)
    reason_code: Mapped[str] = mapped_column(_exact_ascii_string(128), nullable=False)
    idempotency_key_sha256: Mapped[str] = mapped_column(_exact_ascii_string(64), nullable=False)


def _reject_immutable_record_mutation(
    _mapper: Mapper[Any], _connection: Connection, _target: object
) -> None:
    raise ImmutableStockSnapshotGrantError("stock snapshot grant and audit rows are append-only")


def _normalize_utc(target: Any, field_name: str) -> None:
    """Require an aware datetime and normalize it to UTC before ORM persistence."""
    value = getattr(target, field_name)
    if not isinstance(value, datetime):
        raise InvalidStockSnapshotGrantRecord(f"{field_name}_must_be_datetime")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise InvalidStockSnapshotGrantRecord(f"{field_name}_timezone_invalid") from exc
    if value.tzinfo is None or offset is None:
        raise InvalidStockSnapshotGrantRecord(f"{field_name}_must_be_timezone_aware")
    try:
        normalized = value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise InvalidStockSnapshotGrantRecord(f"{field_name}_timezone_invalid") from exc
    setattr(target, field_name, normalized)


def _normalize_created_at(target: Any) -> None:
    """Set the ORM default before insert, then enforce an aware UTC timestamp."""
    if "created_at" not in target.__dict__:
        target.created_at = datetime.now(timezone.utc)
    _normalize_utc(target, "created_at")


def _require_user_reference(value: object, field_name: str) -> None:
    """Match the existing user ID/policy contract without assuming UUID form."""
    if not isinstance(value, str) or not 0 < len(value) <= 36 or value.strip() != value:
        raise InvalidStockSnapshotGrantRecord(f"{field_name}_invalid")


def _validate_common_scope(target: Any) -> None:
    """Validate canonical exact-snapshot symbols at the ORM persistence boundary."""
    if not isinstance(target.market, str) or target.market not in {"SH", "SZ"}:
        raise InvalidStockSnapshotGrantRecord("market_invalid")
    if (
        not isinstance(target.instrument_id, str)
        or _INSTRUMENT_ID.fullmatch(target.instrument_id) is None
        or target.instrument_id[-2:] != target.market
    ):
        raise InvalidStockSnapshotGrantRecord("instrument_id_invalid")
    if (
        not isinstance(target.publication_id, str)
        or _PUBLICATION_ID.fullmatch(target.publication_id) is None
    ):
        raise InvalidStockSnapshotGrantRecord("publication_id_invalid")
    if not isinstance(target.capture_id, str) or _CAPTURE_ID.fullmatch(target.capture_id) is None:
        raise InvalidStockSnapshotGrantRecord("capture_id_invalid")
    if target.purpose != "RESEARCH":
        raise InvalidStockSnapshotGrantRecord("purpose_invalid")
    if (
        isinstance(target.revision, bool)
        or not isinstance(target.revision, int)
        or target.revision < 1
    ):
        raise InvalidStockSnapshotGrantRecord("revision_invalid")
    _normalize_utc(target, "valid_from")
    _normalize_utc(target, "expires_at")
    if target.expires_at <= target.valid_from:
        raise InvalidStockSnapshotGrantRecord("validity_window_invalid")


def _validate_user_grant_insert(
    _mapper: Mapper[Any], _connection: Connection, target: StockSnapshotUserReadGrant
) -> None:
    if (
        target.permission != "data:read"
        or not isinstance(target.dataset_id, str)
        or target.dataset_id not in _DATASET_SOURCE
    ):
        raise InvalidStockSnapshotGrantRecord("user_grant_scope_invalid")
    _require_user_reference(target.user_id, "user_id")
    _validate_common_scope(target)
    _normalize_created_at(target)


def _validate_source_grant_insert(
    _mapper: Mapper[Any], _connection: Connection, target: StockSnapshotSourceResearchGrant
) -> None:
    if (
        not isinstance(target.dataset_id, str)
        or not isinstance(target.source_id, str)
        or _DATASET_SOURCE.get(target.dataset_id) != target.source_id
    ):
        raise InvalidStockSnapshotGrantRecord("source_grant_scope_invalid")
    if (
        not isinstance(target.source_registry_revision, str)
        or _REVISION.fullmatch(target.source_registry_revision) is None
    ):
        raise InvalidStockSnapshotGrantRecord("source_registry_revision_invalid")
    _require_user_reference(target.user_id, "user_id")
    _validate_common_scope(target)
    _normalize_created_at(target)


def _validate_audit_insert(
    _mapper: Mapper[Any], _connection: Connection, target: StockSnapshotGrantAudit
) -> None:
    has_user_grant = target.user_grant_id is not None
    has_source_grant = target.source_grant_id is not None
    if has_user_grant == has_source_grant:
        raise InvalidStockSnapshotGrantRecord("audit_must_reference_exactly_one_grant")
    if not isinstance(target.event_type, str) or target.event_type not in {"ISSUED", "REVOKED"}:
        raise InvalidStockSnapshotGrantRecord("audit_event_type_invalid")
    if target.policy_version != _POLICY_VERSION:
        raise InvalidStockSnapshotGrantRecord("audit_policy_version_invalid")
    expected_revocation_revision = 1 if target.event_type == "ISSUED" else 2
    if (
        isinstance(target.grant_revision, bool)
        or not isinstance(target.grant_revision, int)
        or target.grant_revision < 1
        or isinstance(target.revocation_revision, bool)
        or not isinstance(target.revocation_revision, int)
        or target.revocation_revision != expected_revocation_revision
    ):
        raise InvalidStockSnapshotGrantRecord("audit_revision_invalid")
    if not isinstance(target.reason_code, str) or _REVISION.fullmatch(target.reason_code) is None:
        raise InvalidStockSnapshotGrantRecord("audit_reason_invalid")
    if (
        not isinstance(target.idempotency_key_sha256, str)
        or _SHA256.fullmatch(target.idempotency_key_sha256) is None
    ):
        raise InvalidStockSnapshotGrantRecord("audit_idempotency_hash_invalid")
    _require_user_reference(target.subject_user_id, "subject_user_id")
    _require_user_reference(target.actor_user_id, "actor_user_id")
    _normalize_utc(target, "occurred_at")


for _record in (
    StockSnapshotUserReadGrant,
    StockSnapshotSourceResearchGrant,
    StockSnapshotGrantAudit,
):
    event.listen(_record, "before_update", _reject_immutable_record_mutation)
    event.listen(_record, "before_delete", _reject_immutable_record_mutation)

event.listen(StockSnapshotUserReadGrant, "before_insert", _validate_user_grant_insert)
event.listen(StockSnapshotSourceResearchGrant, "before_insert", _validate_source_grant_insert)
event.listen(StockSnapshotGrantAudit, "before_insert", _validate_audit_insert)
