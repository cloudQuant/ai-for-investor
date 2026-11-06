"""Operator attestation surface: unavailable, with the refusal recorded.

An interrupted sibling change (commit ``398cfaa33``, "wip(market-data):
capability ledger writer, left non-importable at the turn cap") split evidence
resolution into ``capability_ledger_evidence.py`` and deleted the service that
``app/api/data/capability_ledger_admin.py``, ``app/schemas/market_data_capability_ledger.py``
and ``tests/market_data_platform/test_capability_ledger_admin.py`` still import.
With only that module missing, ``app.main`` could not import at all, so nothing
in the application -- including the durable capability gate -- could be started
or tested.

This module restores the import surface without restoring a guess about the
unfinished design.  The open question is left to its owner, and this file
records it verbatim from that commit message:

    "an admin-posted attestation is a caller-chosen value, which is the thing
    AC02/AC03/AC09/AC18 must not accept, so the writer has to come from the
    code path that actually decides the capability"

Until that is decided, every operator append and every operator evidence
preview refuses with a stable code.  A refusal is the only fail-closed
behaviour available here:

* it cannot mint a ``declared``/``installed``/``verified``/``authorized`` bit,
  so it cannot widen what the durable reader grants;
* it does not synthesize an evidence digest whose receipts it has not been
  told how to attribute -- the split's own rollout planes are documented as
  "not recorded" in ``capability_ledger_evidence._REQUIRED_ROLLOUT_PLANES``;
* it never deletes or rewrites a stored ledger revision.

The capability facts a running deployment really does observe are recorded by
``app.services.market_data.capability_ledger_admission``, which appends only
``declared``/``installed`` from the query-admission path and never a
verification or authorization claim.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.market_data.capability_ledger_evidence import (
    CapabilityEvidenceArtifact,
    CapabilityEvidenceFacts,
    CapabilityEvidenceRoute,
    CapabilityEvidenceSummary,
    CapabilityLedgerAdminError,
    CapabilityLedgerStage,
    registry_descriptor_evidence_sha256,
    route_receipts_evidence_sha256,
)
from app.services.market_data.source_policy import MarketDataSourcePolicy

WRITER_UNAVAILABLE = "CAPABILITY_LEDGER_ADMIN_WRITER_UNAVAILABLE"

_UNAVAILABLE_DETAIL: Mapping[str, Any] = {
    "reason": (
        "the operator attestation writer was deleted mid-refactor by commit "
        "398cfaa33; its evidence-plane design is unresolved"
    ),
    "required_decision": (
        "an operator-posted attestation is a caller-chosen value, so the writer "
        "must be re-derived from a durable plane that actually exists before any "
        "declared/installed/verified/authorized bit can be appended here"
    ),
    "recorded_by_running_deployment": ("app.services.market_data.capability_ledger_admission"),
}


class MarketDataCapabilityLedgerAdminService:
    """Refuse every operator append until the unfinished design is decided."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(db, AsyncSession):
            raise TypeError("db must be an AsyncSession")
        self._db = db
        self._clock = clock

    async def append_record(
        self,
        *,
        capability_id: str,
        stage: CapabilityLedgerStage,
        policy: MarketDataSourcePolicy,
        actor_user_id: str,
        effective_until: datetime,
        effective_from: datetime | None = None,
        verified_until: datetime | None = None,
        authorized_until: datetime | None = None,
    ) -> Any:
        """Refuse: appending a lifecycle bit nobody derived is a fabrication."""
        raise CapabilityLedgerAdminError(WRITER_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL)

    async def preview_evidence(
        self,
        *,
        capability_id: str,
        policy: MarketDataSourcePolicy,
        window_end: datetime | None = None,
    ) -> CapabilityEvidenceSummary:
        """Refuse: the preview plane for rollout gates is not settled."""
        raise CapabilityLedgerAdminError(WRITER_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL)

    async def reverify_record(
        self,
        *,
        capability_id: str,
        revision: int,
        policy: MarketDataSourcePolicy,
    ) -> CapabilityEvidenceSummary:
        """Refuse: re-derivation rules for stored rows are still undecided."""
        raise CapabilityLedgerAdminError(WRITER_UNAVAILABLE, detail=_UNAVAILABLE_DETAIL)


__all__ = [
    "CapabilityEvidenceArtifact",
    "CapabilityEvidenceFacts",
    "CapabilityEvidenceRoute",
    "CapabilityEvidenceSummary",
    "CapabilityLedgerAdminError",
    "MarketDataCapabilityLedgerAdminService",
    "WRITER_UNAVAILABLE",
    "registry_descriptor_evidence_sha256",
    "route_receipts_evidence_sha256",
]
