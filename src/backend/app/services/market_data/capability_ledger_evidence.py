"""Checkable durable evidence resolution for capability ledger attestations.

The durable ledger reader treats ``descriptor_sha256`` and ``evidence_sha256``
as facts it can only compare, so the writer has to derive them.  This module
owns that derivation.

* A descriptor always comes from the live server-owned source policy, using the
  reader's own canonical descriptor functions.  A caller never supplies one.
* An evidence digest is derived from durable, immutable market-data rows that
  are re-read and re-checked here: a source snapshot must carry a ``VERIFIED``
  source-authorization attestation, be sealed by a published ``MdPublication``
  whose ``entity_sha256`` still equals the snapshot payload digest, have
  normalized at least one persisted observation revision into a series inside
  the route's axes, and its recorded query receipt must stay inside that route.
  An empty, over-large, drifted, or non-matching set is refused rather than
  summarized as a hash.

Two planes exist because they prove different things, and the surface refuses
anything between them:

``registry-descriptor-v1``
    A canonical reference to the reviewed descriptor this build ships.  It is
    what a ``declared`` or ``installed`` revision may claim; it asserts nothing
    about the outside world beyond this codebase.

``verified-source-route-receipts-v1``
    The durable provider-route receipts described above, selectable again from
    the stored ``capability_id`` plus that record's own ``effective_from``
    window.  A ``verified`` or ``authorized`` revision about one reviewed route
    may claim it only when that route declares an exact family contract pair.

There is deliberately no plane for ``market-data.query-v2``,
``market-data.research-cache-fill``, or ``market-data.research-backtest-bridge``.
Those gates concern the v2 read path, and the schema holds no artifact that
proves a live authenticated read request succeeded while the gate is closed —
provider-route receipts prove collection and normalization, not read serving.
Borrowing a data-plane digest for a read-plane claim is exactly the false green
this ledger exists to prevent, so those stages return
``CAPABILITY_LEDGER_ADMIN_UNSPECIFIED_EVIDENCE`` and name the plane each gate
would need.  Owner decisions 197-O04, O06, and O08 stay open.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_governance import DgProvider
from app.models.market_data_platform import (
    SOURCE_AUTHORIZATION_STATE_VERIFIED,
    MdDataSeries,
    MdObservationRevision,
    MdPublication,
    MdSourceSnapshot,
)
from app.services.market_data.capability_ledger import (
    MARKET_DATA_ONLINE_FETCH_CAPABILITY,
    MARKET_DATA_QUERY_V2_CAPABILITY,
    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY,
    MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY,
    ledger_canonical_sha256,
    rollout_capability_descriptor_sha256,
    route_capability_descriptor_sha256,
    route_capability_id,
)
from app.services.market_data.publication import PUBLICATION_SOURCE_SNAPSHOT
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
)

UTC = timezone.utc

CapabilityLedgerStage = Literal[
    "declared",
    "installed",
    "verified",
    "authorized",
    "retired",
]

_LEDGER_EVIDENCE_VERSION = "market-data-capability-ledger-evidence-v1"
_EVIDENCE_KIND_REGISTRY_DESCRIPTOR = "registry-descriptor-v1"
_EVIDENCE_KIND_ROUTE_RECEIPTS = "verified-source-route-receipts-v1"
_ROUTE_CAPABILITY_PREFIX = "market-data.route:"
_MAX_EVIDENCE_ARTIFACTS = 500

_ROLLOUT_CAPABILITY_IDS = frozenset(
    {
        MARKET_DATA_QUERY_V2_CAPABILITY,
        MARKET_DATA_ONLINE_FETCH_CAPABILITY,
        MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY,
        MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY,
    }
)

#: The plane each rollout gate would need before a verification or
#: authorization claim can be honest.  None of these is persisted today, so
#: ``_require_plane`` refuses rather than substituting a weaker digest.
_REQUIRED_ROLLOUT_PLANES: Mapping[str, str] = {
    MARKET_DATA_QUERY_V2_CAPABILITY: (
        "authenticated v2 read-serving receipt (197-O04: not recorded)"
    ),
    MARKET_DATA_ONLINE_FETCH_CAPABILITY: (
        "aggregate of every reviewed route's provider receipts "
        "(197-O06: per-route receipts exist, an aggregate plane does not)"
    ),
    MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY: (
        "research-cache-fill writer receipt (197-O08: not recorded)"
    ),
    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY: (
        "query-contract bridge receipt (197-O08: not recorded)"
    ),
}


class CapabilityLedgerAdminError(RuntimeError):
    """One stable, non-secret reason why an attestation could not be appended."""

    def __init__(self, code: str, *, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail: dict[str, Any] = dict(detail or {})


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceArtifact:
    """One durable source receipt that contributed to an evidence digest."""

    snapshot_id: str
    provider_id: str
    payload_sha256: str
    source_authorization_descriptor_sha256: str
    retrieved_at: datetime
    visibility_sequence: int

    def as_pre_image(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "provider_id": self.provider_id,
            "payload_sha256": self.payload_sha256,
            "source_authorization_descriptor_sha256": (self.source_authorization_descriptor_sha256),
            "retrieved_at": _as_utc(self.retrieved_at).isoformat(),
            "visibility_sequence": self.visibility_sequence,
        }


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceRoute:
    """One reviewed route's durable receipt set inside the evidence digest."""

    capability_id: str
    route_id: str
    descriptor_sha256: str
    artifacts: tuple[CapabilityEvidenceArtifact, ...]

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    def as_public(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "route_id": self.route_id,
            "artifact_count": self.artifact_count,
        }

    def as_pre_image(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "route_id": self.route_id,
            "descriptor_sha256": self.descriptor_sha256,
            "artifacts": [artifact.as_pre_image() for artifact in self.artifacts],
        }


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceSummary:
    """What the durable evidence plane currently proves for one capability."""

    capability_id: str
    descriptor_sha256: str
    evidence_kind: str
    evidence_sha256: str
    artifact_count: int
    window_end: datetime
    routes: tuple[dict[str, Any], ...] = ()
    matches_stored: bool | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityEvidenceFacts:
    """The live registry facts one capability ID resolves to."""

    capability_id: str
    descriptor_sha256: str
    scope: str
    route: MarketDataProviderRoute | None


@dataclass(frozen=True, slots=True)
class _SeriesAxes:
    canonical_id: str
    semantic_identity: Mapping[str, Any]


class CapabilityEvidenceResolver:
    """Resolve descriptors and evidence digests from durable state only."""

    def __init__(self, db: AsyncSession) -> None:
        if not isinstance(db, AsyncSession):
            raise TypeError("db must be an AsyncSession")
        self._db = db

    async def describe(
        self,
        *,
        capability_id: str,
        policy: MarketDataSourcePolicy,
    ) -> CapabilityEvidenceFacts:
        """Return the descriptor this build requires for one capability ID."""
        normalized = _required_text(capability_id, field_name="capability_id", maximum=192)
        if normalized in _ROLLOUT_CAPABILITY_IDS:
            return CapabilityEvidenceFacts(
                capability_id=normalized,
                descriptor_sha256=rollout_capability_descriptor_sha256(normalized),
                scope="rollout",
                route=None,
            )
        if normalized.startswith(_ROUTE_CAPABILITY_PREFIX):
            route_id = normalized[len(_ROUTE_CAPABILITY_PREFIX) :]
            route = next((item for item in policy.routes if item.route_id == route_id), None)
            if route is None:
                raise CapabilityLedgerAdminError(
                    "CAPABILITY_LEDGER_ADMIN_ROUTE_UNDECLARED",
                    detail={"route_id": route_id},
                )
            return CapabilityEvidenceFacts(
                capability_id=normalized,
                descriptor_sha256=route_capability_descriptor_sha256(route),
                scope="route",
                route=route,
            )
        raise CapabilityLedgerAdminError(
            "CAPABILITY_LEDGER_ADMIN_CAPABILITY_UNKNOWN",
            detail={"capability_id": normalized},
        )

    async def registry_digest(
        self,
        *,
        facts: CapabilityEvidenceFacts,
        window_end: datetime,
    ) -> CapabilityEvidenceSummary:
        """Return the registry-reference digest a declared record may claim."""
        return CapabilityEvidenceSummary(
            capability_id=facts.capability_id,
            descriptor_sha256=facts.descriptor_sha256,
            evidence_kind=_EVIDENCE_KIND_REGISTRY_DESCRIPTOR,
            evidence_sha256=registry_descriptor_evidence_sha256(
                capability_id=facts.capability_id,
                descriptor_sha256=facts.descriptor_sha256,
                window_end=window_end,
            ),
            artifact_count=0,
            window_end=window_end,
        )

    async def receipt_digest(
        self,
        *,
        facts: CapabilityEvidenceFacts,
        policy: MarketDataSourcePolicy,
        window_end: datetime,
    ) -> CapabilityEvidenceSummary:
        """Return the durable receipt digest one reviewed route can claim."""
        self._require_plane(facts)
        route = facts.route
        if route is None:
            raise CapabilityLedgerAdminError(
                "CAPABILITY_LEDGER_ADMIN_CAPABILITY_UNKNOWN",
                detail={"capability_id": facts.capability_id},
            )
        entry = await collect_route_receipts(self._db, route, policy, window_end)
        return CapabilityEvidenceSummary(
            capability_id=facts.capability_id,
            descriptor_sha256=facts.descriptor_sha256,
            evidence_kind=_EVIDENCE_KIND_ROUTE_RECEIPTS,
            evidence_sha256=route_receipts_evidence_sha256(
                capability_id=facts.capability_id,
                descriptor_sha256=facts.descriptor_sha256,
                window_end=window_end,
                routes=(entry,),
            ),
            artifact_count=entry.artifact_count,
            window_end=window_end,
            routes=(entry.as_public(),),
        )

    def _require_plane(self, facts: CapabilityEvidenceFacts) -> None:
        """Refuse a verification claim whose evidence plane was never built."""
        if facts.scope == "rollout":
            raise CapabilityLedgerAdminError(
                "CAPABILITY_LEDGER_ADMIN_UNSPECIFIED_EVIDENCE",
                detail={
                    "capability_id": facts.capability_id,
                    "required_evidence_plane": _REQUIRED_ROLLOUT_PLANES.get(
                        facts.capability_id, "unmapped rollout capability"
                    ),
                },
            )
        route = facts.route
        if route is None:
            return
        if route.family_id is None or route.family_contract_version is None:
            raise CapabilityLedgerAdminError(
                "CAPABILITY_LEDGER_ADMIN_UNATTRIBUTED_ROUTE",
                detail={
                    "route_id": route.route_id,
                    "reason": (
                        "the reviewed route declares no exact family contract pair, "
                        "so no durable receipt set can be attributed to it"
                    ),
                },
            )


def registry_descriptor_evidence_sha256(
    *,
    capability_id: str,
    descriptor_sha256: str,
    window_end: datetime,
) -> str:
    """Return the canonical registry reference for one activation window."""
    return ledger_canonical_sha256(
        {
            "version": _LEDGER_EVIDENCE_VERSION,
            "evidence_kind": _EVIDENCE_KIND_REGISTRY_DESCRIPTOR,
            "capability_id": capability_id,
            "descriptor_sha256": descriptor_sha256,
            "window_end": _as_utc(window_end).isoformat(),
        }
    )


def route_receipts_evidence_sha256(
    *,
    capability_id: str,
    descriptor_sha256: str,
    window_end: datetime,
    routes: Sequence[CapabilityEvidenceRoute],
) -> str:
    return ledger_canonical_sha256(
        {
            "version": _LEDGER_EVIDENCE_VERSION,
            "evidence_kind": _EVIDENCE_KIND_ROUTE_RECEIPTS,
            "capability_id": capability_id,
            "descriptor_sha256": descriptor_sha256,
            "window_end": _as_utc(window_end).isoformat(),
            "route_evidence": [route.as_pre_image() for route in routes],
        }
    )


def is_registry_descriptor_evidence(
    *,
    capability_id: str,
    descriptor_sha256: str,
    window_end: datetime,
    evidence_sha256: str,
) -> bool:
    """Return whether a stored digest is the registry reference for this row."""
    return (
        registry_descriptor_evidence_sha256(
            capability_id=capability_id,
            descriptor_sha256=descriptor_sha256,
            window_end=window_end,
        )
        == evidence_sha256
    )


async def collect_route_receipts(
    db: AsyncSession,
    route: MarketDataProviderRoute,
    policy: MarketDataSourcePolicy,
    window_end: datetime,
) -> CapabilityEvidenceRoute:
    """Collect the durable verified receipts attributable to one route."""
    rows = (
        await db.execute(
            select(
                MdSourceSnapshot.id,
                DgProvider.provider_id,
                MdSourceSnapshot.payload_sha256,
                MdSourceSnapshot.source_authorization_descriptor_sha256,
                MdSourceSnapshot.retrieved_at,
                MdSourceSnapshot.request_json,
                MdPublication.entity_sha256,
                MdPublication.visibility_sequence,
            )
            .join(DgProvider, DgProvider.id == MdSourceSnapshot.provider_id)
            .join(
                MdPublication,
                and_(
                    MdPublication.entity_type == PUBLICATION_SOURCE_SNAPSHOT,
                    MdPublication.entity_id == MdSourceSnapshot.id,
                ),
            )
            .where(
                MdSourceSnapshot.source_authorization_state
                == SOURCE_AUTHORIZATION_STATE_VERIFIED,
                MdSourceSnapshot.source_authorization_descriptor_sha256.is_not(None),
                MdSourceSnapshot.retrieved_at <= window_end,
                MdPublication.published_at.is_not(None),
                MdPublication.visibility_sequence.is_not(None),
                DgProvider.provider_id.in_(
                    tuple(sorted(route.expected_result_provider_ids))
                ),
            )
            .order_by(MdSourceSnapshot.id)
            .limit(_MAX_EVIDENCE_ARTIFACTS + 1)
        )
    ).all()
    if len(rows) > _MAX_EVIDENCE_ARTIFACTS:
        raise CapabilityLedgerAdminError(
            "CAPABILITY_LEDGER_ADMIN_EVIDENCE_UNBOUNDED",
            detail={"route_id": route.route_id},
        )
    candidates = [
        row for row in rows if _query_axes_match_route(query=_mapping(row[5]), route=route, policy=policy)
    ]
    series_by_snapshot = await _series_axes_by_snapshot(
        db, [str(row[0]) for row in candidates]
    )
    artifacts: list[CapabilityEvidenceArtifact] = []
    for row in candidates:
        snapshot_id = str(row[0])
        payload_sha256 = str(row[2])
        # The sealing receipt must still name the payload it published.
        if str(row[6]) != payload_sha256:
            raise CapabilityLedgerAdminError(
                "CAPABILITY_LEDGER_ADMIN_EVIDENCE_INTEGRITY",
                detail={"route_id": route.route_id, "snapshot_id": snapshot_id},
            )
        series_axes = series_by_snapshot.get(snapshot_id, ())
        if not any(_series_matches_route(axes=axes, route=route) for axes in series_axes):
            continue
        artifacts.append(
            CapabilityEvidenceArtifact(
                snapshot_id=snapshot_id,
                provider_id=str(row[1]),
                payload_sha256=payload_sha256,
                source_authorization_descriptor_sha256=_require_sha256(row[3]),
                retrieved_at=_as_utc(row[4]),
                visibility_sequence=int(row[7]),
            )
        )
    if not artifacts:
        raise CapabilityLedgerAdminError(
            "CAPABILITY_LEDGER_ADMIN_EVIDENCE_MISSING",
            detail={"route_id": route.route_id},
        )
    return CapabilityEvidenceRoute(
        capability_id=route_capability_id(route.route_id),
        route_id=route.route_id,
        descriptor_sha256=route_capability_descriptor_sha256(route),
        artifacts=tuple(artifacts),
    )


async def _series_axes_by_snapshot(
    db: AsyncSession,
    snapshot_ids: Sequence[str],
) -> Mapping[str, tuple[_SeriesAxes, ...]]:
    """Return the persisted fact series each candidate receipt normalized into."""
    if not snapshot_ids:
        return {}
    rows = (
        await db.execute(
            select(
                MdObservationRevision.source_snapshot_id,
                MdDataSeries.canonical_id,
                MdDataSeries.semantic_identity_json,
            )
            .join(MdDataSeries, MdDataSeries.id == MdObservationRevision.series_id)
            .where(MdObservationRevision.source_snapshot_id.in_(tuple(snapshot_ids)))
            .order_by(MdObservationRevision.source_snapshot_id, MdDataSeries.canonical_id)
        )
    ).all()
    grouped: dict[str, list[_SeriesAxes]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(
            _SeriesAxes(canonical_id=str(row[1]), semantic_identity=_mapping(row[2]))
        )
    return {snapshot_id: tuple(entries) for snapshot_id, entries in grouped.items()}


def _query_axes_match_route(
    *,
    query: Mapping[str, Any],
    route: MarketDataProviderRoute,
    policy: MarketDataSourcePolicy,
) -> bool:
    """Return whether one durable query receipt stayed inside the reviewed route."""
    resolved = query.get("resolved_query")
    if not isinstance(resolved, Mapping):
        return False
    if resolved.get("source_policy_id") != policy.policy_id:
        return False
    for key, axis in (
        ("data_kind", route.data_kinds),
        ("frequency", route.frequencies),
        ("adjustment", route.adjustments),
        ("price_basis", route.price_bases),
        ("currency", route.currencies),
        ("unit", route.units),
    ):
        value = resolved.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or value not in axis:
            return False
    family_id = resolved.get("family_id")
    family_version = resolved.get("family_contract_version")
    if family_id != route.family_id or family_version != route.family_contract_version:
        return False
    identity = resolved.get("identity")
    if not isinstance(identity, Mapping):
        return False
    if not _axis_contains(route.asset_types, identity.get("asset_type")):
        return False
    return _axis_contains(route.markets, identity.get("market"))


def _series_matches_route(
    *,
    axes: _SeriesAxes,
    route: MarketDataProviderRoute,
) -> bool:
    """Confirm the persisted fact series really belongs to the route's axes."""
    if not axes.canonical_id:
        return False
    if not _axis_contains(route.asset_types, axes.semantic_identity.get("asset_type")):
        return False
    return _axis_contains(route.markets, axes.semantic_identity.get("market"))


def _axis_contains(axis: Iterable[str | None], value: object) -> bool:
    """Treat an absent axis selector as unconstrained, but reject a bad value."""
    if value is None:
        return True
    return isinstance(value, str) and value in set(axis)


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _require_sha256(value: object) -> str:
    normalized = str(value or "")
    if len(normalized) != 64:
        raise CapabilityLedgerAdminError("CAPABILITY_LEDGER_ADMIN_EVIDENCE_INTEGRITY")
    return normalized


def _required_text(value: object, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field_name} must be a non-empty string up to {maximum} characters")
    return normalized


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
