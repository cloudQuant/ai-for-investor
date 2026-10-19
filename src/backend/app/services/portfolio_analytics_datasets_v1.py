"""Persist immutable, owner-bound user-supplied offline V1 facts datasets."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_analytics_dataset import PortfolioAnalyticsDatasetV1
from app.models.portfolio_composition import PortfolioCompositionVersion
from app.schemas.portfolio_analytics_v1 import (
    PortfolioAnalyticsDatasetCreateV1,
    PortfolioAnalyticsFactsV1,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATASET_REF = re.compile(r"^afi1d:[0-9a-f]{24}$")
_SOURCE_TYPES = frozenset({"research", "imported", "paper"})
_MAX_FACTS_BYTES = 768_000


class PortfolioAnalyticsDatasetV1Error(RuntimeError):
    """Finite data-import error without echoing user-supplied facts."""

    def __init__(self, code: str, http_status: int) -> None:
        self.code = code
        self.http_status = http_status
        super().__init__(code)


class PortfolioAnalyticsDatasetV1Service:
    """Store canonical V1 facts under one exact owner and composition version."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        owner_subject: str,
        membership: PortfolioCompositionVersion,
        payload: PortfolioAnalyticsDatasetCreateV1,
    ) -> dict[str, Any]:
        if (
            type(owner_subject) is not str
            or not owner_subject
            or owner_subject != membership.owner_subject
        ):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_NOT_FOUND", 404)
        facts = payload.facts
        self._validate_membership_binding(membership, facts)
        encoded = _canonical_json(facts.model_dump(mode="json"))
        if len(encoded) > _MAX_FACTS_BYTES:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_TOO_LARGE", 413)
        facts_json = encoded.decode("ascii")
        facts_sha256 = hashlib.sha256(encoded).hexdigest()
        idempotency_sha256 = _digest(payload.idempotency_key)
        dataset_ref = self._dataset_ref(
            owner_subject,
            membership.portfolio_ref,
            membership.membership_version,
            membership.membership_sha256,
            idempotency_sha256,
        )
        existing = await self._db.scalar(
            select(PortfolioAnalyticsDatasetV1).where(
                PortfolioAnalyticsDatasetV1.owner_subject == owner_subject,
                PortfolioAnalyticsDatasetV1.portfolio_ref == membership.portfolio_ref,
                PortfolioAnalyticsDatasetV1.membership_version == membership.membership_version,
                PortfolioAnalyticsDatasetV1.idempotency_key_sha256 == idempotency_sha256,
            )
        )
        if existing is not None:
            return self._existing_or_conflict(
                existing,
                owner_subject,
                membership,
                dataset_ref,
                facts_sha256,
            )

        row = PortfolioAnalyticsDatasetV1(
            dataset_ref=dataset_ref,
            owner_subject=owner_subject,
            portfolio_ref=membership.portfolio_ref,
            membership_version=membership.membership_version,
            membership_sha256=membership.membership_sha256,
            source_type=facts.source_mode,
            source_trust=payload.source_trust,
            source_ref=facts.source_ref,
            source_version=facts.source_version,
            source_generation=facts.source_generation,
            facts_snapshot_ref=facts.facts_snapshot_ref,
            facts_sha256=facts_sha256,
            facts_json=facts_json,
            idempotency_key_sha256=idempotency_sha256,
        )
        self._db.add(row)
        try:
            await self._db.commit()
        except IntegrityError:
            await self._db.rollback()
            winner = await self._db.scalar(
                select(PortfolioAnalyticsDatasetV1).where(
                    PortfolioAnalyticsDatasetV1.owner_subject == owner_subject,
                    PortfolioAnalyticsDatasetV1.portfolio_ref == membership.portfolio_ref,
                    PortfolioAnalyticsDatasetV1.membership_version
                    == membership.membership_version,
                    PortfolioAnalyticsDatasetV1.idempotency_key_sha256 == idempotency_sha256,
                )
            )
            if winner is not None:
                return self._existing_or_conflict(
                    winner,
                    owner_subject,
                    membership,
                    dataset_ref,
                    facts_sha256,
                )
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_CONFLICT", 409) from None
        await self._db.refresh(row)
        return self._metadata(row)

    async def get_owned(
        self,
        owner_subject: str,
        membership: PortfolioCompositionVersion,
        dataset_ref: str,
    ) -> tuple[PortfolioAnalyticsDatasetV1, PortfolioAnalyticsFactsV1]:
        if (
            type(owner_subject) is not str
            or not owner_subject
            or owner_subject != membership.owner_subject
        ):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_NOT_FOUND", 404)
        if type(dataset_ref) is not str or _DATASET_REF.fullmatch(dataset_ref) is None:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_NOT_FOUND", 404)
        row = await self._db.scalar(
            select(PortfolioAnalyticsDatasetV1).where(
                PortfolioAnalyticsDatasetV1.dataset_ref == dataset_ref,
                PortfolioAnalyticsDatasetV1.owner_subject == owner_subject,
                PortfolioAnalyticsDatasetV1.portfolio_ref == membership.portfolio_ref,
                PortfolioAnalyticsDatasetV1.membership_version == membership.membership_version,
                PortfolioAnalyticsDatasetV1.membership_sha256 == membership.membership_sha256,
                PortfolioAnalyticsDatasetV1.source_type == membership.source_type,
                PortfolioAnalyticsDatasetV1.source_trust == "USER_SUPPLIED_OFFLINE",
            )
        )
        if row is None:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_NOT_FOUND", 404)
        facts = self._decode_and_verify(row, membership)
        return row, facts

    @staticmethod
    def analytics_member_ref(kind: str, ref: str) -> str:
        """Return the canonical opaque member key used in V1 facts rows."""

        encoded = _canonical_json({"kind": kind, "ref": ref})
        return "member:" + hashlib.sha256(encoded).hexdigest()

    def _validate_membership_binding(
        self, membership: PortfolioCompositionVersion, facts: PortfolioAnalyticsFactsV1
    ) -> None:
        if membership.source_type not in _SOURCE_TYPES:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_OFFLINE_SOURCE_REQUIRED", 403)
        if facts.source_mode != membership.source_type:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_SOURCE_MODE_MISMATCH", 422)
        if facts.portfolio_ref != membership.portfolio_ref:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_PORTFOLIO_MISMATCH", 422)
        if (
            facts.membership.portfolio_ref != membership.portfolio_ref
            or facts.membership.membership_version != membership.membership_version
        ):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_MEMBERSHIP_MISMATCH", 422)
        try:
            expected_refs = sorted(
                self.analytics_member_ref(member["kind"], member["ref"])
                for member in membership.members
                if type(member) is dict and set(member) == {"kind", "ref"}
            )
        except (KeyError, TypeError, ValueError):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_MEMBERSHIP_UNAVAILABLE", 503) from None
        if len(expected_refs) != len(membership.members) or facts.membership.member_refs != expected_refs:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_MEMBERSHIP_MISMATCH", 422)

    def _decode_and_verify(
        self,
        row: PortfolioAnalyticsDatasetV1,
        membership: PortfolioCompositionVersion,
    ) -> PortfolioAnalyticsFactsV1:
        if (
            row.owner_subject != membership.owner_subject
            or row.portfolio_ref != membership.portfolio_ref
            or row.membership_version != membership.membership_version
            or row.membership_sha256 != membership.membership_sha256
            or type(row.facts_json) is not str
            or type(row.facts_sha256) is not str
            or _SHA256.fullmatch(row.facts_sha256) is None
        ):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_INTEGRITY_ERROR", 503)
        try:
            encoded = row.facts_json.encode("ascii", errors="strict")
            decoded = json.loads(row.facts_json)
            if _canonical_json(decoded) != encoded:
                raise ValueError("noncanonical")
            facts = PortfolioAnalyticsFactsV1.model_validate(decoded)
        except (UnicodeError, ValueError, TypeError, RecursionError):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_INTEGRITY_ERROR", 503) from None
        if (
            hashlib.sha256(encoded).hexdigest() != row.facts_sha256
            or row.source_trust != "USER_SUPPLIED_OFFLINE"
            or row.source_type != membership.source_type
            or row.source_ref != facts.source_ref
            or row.source_version != facts.source_version
            or row.source_generation != facts.source_generation
            or row.facts_snapshot_ref != facts.facts_snapshot_ref
        ):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_INTEGRITY_ERROR", 503)
        self._validate_membership_binding(membership, facts)
        return facts

    def _existing_or_conflict(
        self,
        row: PortfolioAnalyticsDatasetV1,
        owner_subject: str,
        membership: PortfolioCompositionVersion,
        dataset_ref: str,
        facts_sha256: str,
    ) -> dict[str, Any]:
        if (
            row.owner_subject != owner_subject
            or row.membership_sha256 != membership.membership_sha256
            or row.dataset_ref != dataset_ref
            or row.facts_sha256 != facts_sha256
        ):
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_IDEMPOTENCY_CONFLICT", 409)
        self._decode_and_verify(row, membership)
        if self._metadata(row)["facts_sha256"] != facts_sha256:
            raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_IDEMPOTENCY_CONFLICT", 409)
        return self._metadata(row)

    @staticmethod
    def _dataset_ref(
        owner_subject: str,
        portfolio_ref: str,
        membership_version: int,
        membership_sha256: str,
        idempotency_sha256: str,
    ) -> str:
        seed = _canonical_json(
            {
                "idempotency_key_sha256": idempotency_sha256,
                "membership_sha256": membership_sha256,
                "membership_version": membership_version,
                "owner_subject": owner_subject,
                "portfolio_ref": portfolio_ref,
                "version": 1,
            }
        )
        return "afi1d:" + hashlib.sha256(seed).hexdigest()[:24]

    @staticmethod
    def _metadata(row: PortfolioAnalyticsDatasetV1) -> dict[str, Any]:
        return {
            "dataset_ref": row.dataset_ref,
            "facts_sha256": row.facts_sha256,
            "facts_snapshot_ref": row.facts_snapshot_ref,
            "membership_sha256": row.membership_sha256,
            "membership_version": row.membership_version,
            "portfolio_ref": row.portfolio_ref,
            "source_generation": row.source_generation,
            "source_ref": row.source_ref,
            "source_trust": row.source_trust,
            "source_type": row.source_type,
            "source_version": row.source_version,
            "created_at": row.created_at.isoformat(),
        }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError) as error:
        raise PortfolioAnalyticsDatasetV1Error("ANALYTICS_DATASET_INVALID", 422) from error


