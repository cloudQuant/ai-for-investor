"""Durable admission observations written by the code path that serves queries.

``MarketDataCapabilityLedger`` is a pure reader and the reviewed design
(``docs/iterations/迭代197-本地优先市场数据中台/DESIGN.md``) forbids a request,
an environment variable, or a provider name from minting a deployment
attestation.  That forbiddance is about the two lifecycle facts a request
genuinely cannot know -- ``verified`` and ``authorized`` -- not about the two
facts the running process does know:

* ``declared``: this build's server-owned source policy contains the capability
  (the four rollout capability IDs exist in code, and the route appears in the
  resolved reviewed policy).
* ``installed``: the runtime surface that would execute the capability is really
  loaded in this process -- the query service module imported, or the route's
  provider adapter object is present and callable.

This module records exactly those two observed facts, and only those, from the
v2 query admission path.  Every other lifecycle bit stays ``false`` with
``NULL`` windows, so an observation row can never make a capability effective:
the durable reader still returns ``CAPABILITY_NOT_VERIFIED`` instead of
``CAPABILITY_LEDGER_MISSING``.  Recording an honest refusal is still required by
the acceptance questions, which ask what capability was actually available and
attested at a given instant; a deployment whose ledger is empty cannot answer
them even after its code has shipped.

Scope of the claim, stated plainly because it must not be over-read: only
queries that arrive *after* this code is deployed can be recorded.  Nothing here
reconstructs history, backfills a row, or converts a row count into evidence
that a read succeeded.

Anti-false-green rules enforced here:

* No caller supplies a capability ID, descriptor, evidence digest, lifecycle
  flag, actor, or window.  The descriptor is re-derived with the reader's own
  canonical descriptor functions over the *live* reviewed policy, and the
  evidence digest is a canonical hash of the observed pre-image only.
* Writes are idempotent per ``(capability_id, versioned pre-image)``: one build
  appends at most one row per capability.  The durable ``(capability_id,
  revision)`` unique constraint is the cross-worker tiebreak, and a losing
  insert is treated as "already recorded", never as a failure.
* A write is skipped whenever it would create two current records for one
  capability (the reader reports ``CAPABILITY_LEDGER_AMBIGUOUS`` and disables
  it), so an open-ended operator record is never disturbed.  The bounded
  observation window also guarantees an operator append is never permanently
  blocked by these rows.
* Any database or introspection error is swallowed after a rollback.  A refusal
  to record must never change the served response, must never open a gate, and
  must never let a request proceed that the durable reader disabled.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data_platform import MdCapabilityLedgerEntry
from app.services.market_data.capability_ledger import (
    MARKET_DATA_DEFAULT_POLICY_ID,
    MARKET_DATA_ONLINE_FETCH_CAPABILITY,
    MARKET_DATA_QUERY_V2_CAPABILITY,
    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY,
    MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY,
    MarketDataCapabilityEvaluation,
    ledger_canonical_sha256,
    rollout_capability_descriptor_sha256,
    route_capability_descriptor_sha256,
    route_capability_id,
)
from app.services.market_data.source_policy import (
    MarketDataProviderRoute,
    MarketDataSourcePolicy,
)

logger = logging.getLogger(__name__)

UTC = timezone.utc

ADMISSION_OBSERVATION_VERSION = "market-data-capability-admission-v1"
ADMISSION_OBSERVATION_KIND = "observed-query-admission"
DEFAULT_OBSERVATION_WINDOW = timedelta(minutes=10)

_ROLLOUT_CAPABILITY_IDS = (
    MARKET_DATA_QUERY_V2_CAPABILITY,
    MARKET_DATA_ONLINE_FETCH_CAPABILITY,
    MARKET_DATA_RESEARCH_CACHE_FILL_CAPABILITY,
    MARKET_DATA_RESEARCH_BACKTEST_BRIDGE_CAPABILITY,
)


@dataclass(frozen=True, slots=True)
class AdmissionObservation:
    """One observed lifecycle fact set, with its derived versioned pre-image."""

    capability_id: str
    scope: str
    route_id: str | None
    descriptor_sha256: str
    declared: bool
    installed: bool
    installed_surface: str | None

    def as_pre_image(self) -> dict[str, Any]:
        """Return the canonical hash input, free of any caller-supplied value."""
        return {
            "version": ADMISSION_OBSERVATION_VERSION,
            "observation_kind": ADMISSION_OBSERVATION_KIND,
            "capability_id": self.capability_id,
            "scope": self.scope,
            "policy_id": MARKET_DATA_DEFAULT_POLICY_ID,
            "route_id": self.route_id,
            "descriptor_sha256": self.descriptor_sha256,
            "declared_observed": self.declared,
            "installed_observed": self.installed,
            "installed_surface": self.installed_surface,
        }

    @property
    def evidence_sha256(self) -> str:
        """Hash only observed facts; a request body is never part of the input."""
        return ledger_canonical_sha256(self.as_pre_image())


@dataclass(frozen=True, slots=True)
class AdmissionObservationResult:
    """What one admission observation pass durably recorded, for tests and logs."""

    recorded_capability_ids: tuple[str, ...]
    skipped_capability_ids: tuple[str, ...]

    @property
    def recorded_count(self) -> int:
        return len(self.recorded_capability_ids)


def _observations(
    evaluation: MarketDataCapabilityEvaluation,
) -> tuple[AdmissionObservation, ...]:
    """Derive the observed fact set from one real durable evaluation.

    Only the server-owned policy carried by the evaluation is inspected, so a
    request body can add neither a capability nor an axis to a descriptor.
    """
    policy = _reviewed_policy(evaluation)
    if policy is None:
        return ()
    query_surface = _installed_query_surface()
    observations: list[AdmissionObservation] = [
        AdmissionObservation(
            capability_id=capability_id,
            scope="rollout",
            route_id=None,
            descriptor_sha256=rollout_capability_descriptor_sha256(capability_id),
            declared=True,
            installed=_rollout_is_installed(capability_id, policy=policy, surface=query_surface),
            installed_surface=query_surface,
        )
        for capability_id in _ROLLOUT_CAPABILITY_IDS
    ]
    observations.extend(
        AdmissionObservation(
            capability_id=route_capability_id(route.route_id),
            scope="route",
            route_id=route.route_id,
            descriptor_sha256=route_capability_descriptor_sha256(route),
            declared=True,
            installed=_route_adapter_is_installed(route),
            installed_surface=_adapter_surface(route),
        )
        for route in policy.routes
    )
    return tuple(observations)


def _reviewed_policy(evaluation: MarketDataCapabilityEvaluation) -> MarketDataSourcePolicy | None:
    """Resolve the exact reviewed policy the reader also resolved, or ``None``."""
    registry = getattr(evaluation, "effective_source_policies", None)
    resolve = getattr(registry, "resolve", None)
    if not callable(resolve):
        return None
    try:
        policy = resolve(MARKET_DATA_DEFAULT_POLICY_ID)
    except Exception:
        # An unresolvable reviewed policy is a refusal to observe, not a licence
        # to describe a capability the reader cannot see.
        return None
    return policy if isinstance(policy, MarketDataSourcePolicy) else None


def _installed_query_surface() -> str | None:
    """Return the loaded v2 query runtime surface, or ``None`` when absent."""
    try:
        from app.services.market_data.query_service import MarketDataQueryService
    except Exception:
        return None
    return f"{MarketDataQueryService.__module__}.{MarketDataQueryService.__qualname__}"


def _rollout_is_installed(
    capability_id: str,
    *,
    policy: MarketDataSourcePolicy,
    surface: str | None,
) -> bool:
    """Judge installation from the runtime surface that would serve the rollout."""
    if surface is None:
        return False
    if capability_id == MARKET_DATA_QUERY_V2_CAPABILITY:
        return True
    # Online collection, cache fill, and the research bridge all require a
    # reviewed route whose provider adapter really exists in this process.
    return any(_route_adapter_is_installed(route) for route in policy.routes)


def _route_adapter_is_installed(route: MarketDataProviderRoute) -> bool:
    adapter = getattr(route, "adapter", None)
    return callable(getattr(adapter, "fetch", None))


def _adapter_surface(route: MarketDataProviderRoute) -> str | None:
    adapter = getattr(route, "adapter", None)
    if adapter is None:
        return None
    return f"{type(adapter).__module__}.{type(adapter).__qualname__}"


async def _existing_rows(
    session: AsyncSession,
    capability_ids: Sequence[str],
) -> Mapping[str, tuple[tuple[int, str, datetime, datetime | None], ...]]:
    """Read the stored pre-images and activation windows for these capabilities."""
    rows = (
        await session.execute(
            select(
                MdCapabilityLedgerEntry.capability_id,
                MdCapabilityLedgerEntry.revision,
                MdCapabilityLedgerEntry.evidence_sha256,
                MdCapabilityLedgerEntry.effective_from,
                MdCapabilityLedgerEntry.effective_until,
            ).where(MdCapabilityLedgerEntry.capability_id.in_(tuple(capability_ids)))
        )
    ).all()
    grouped: dict[str, list[tuple[int, str, datetime, datetime | None]]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(
            (int(row[1]), str(row[2]), _as_utc(row[3]), None if row[4] is None else _as_utc(row[4]))
        )
    return {capability_id: tuple(entries) for capability_id, entries in grouped.items()}


def _already_recorded(
    entries: Sequence[tuple[int, str, datetime, datetime | None]],
    observation: AdmissionObservation,
) -> bool:
    """Return whether this exact versioned pre-image is already durable."""
    recorded = observation.evidence_sha256
    return any(entry[1] == recorded for entry in entries)


def _window_is_free(
    entries: Sequence[tuple[int, str, datetime, datetime | None]],
    *,
    effective_from: datetime,
    effective_until: datetime,
) -> bool:
    """Refuse a window that would make two records current for one capability."""
    return not any(
        entry[2] < effective_until and (entry[3] is None or entry[3] > effective_from)
        for entry in entries
    )


_WRITE_LOCK = asyncio.Lock()


async def record_admission_observations(
    db: AsyncSession,
    evaluation: object,
    *,
    clock: Callable[[], datetime] | None = None,
    observation_window: timedelta = DEFAULT_OBSERVATION_WINDOW,
) -> AdmissionObservationResult | None:
    """Record the admission observation without ever affecting the served query.

    Any unexpected failure is logged and reported as a skip.  The observation is
    a durable side effect of an admission decision; losing it must never turn a
    fail-closed refusal into a 500, and must never turn a refusal into a grant.
    """
    try:
        return await _record_admission_observations(
            db,
            evaluation,
            clock=clock,
            observation_window=observation_window,
        )
    except Exception as exc:
        logger.warning(
            "market-data capability admission observation skipped: %s",
            type(exc).__name__,
        )
        return AdmissionObservationResult(recorded_capability_ids=(), skipped_capability_ids=())


async def _record_admission_observations(
    db: AsyncSession,
    evaluation: object,
    *,
    clock: Callable[[], datetime] | None,
    observation_window: timedelta,
) -> AdmissionObservationResult | None:
    """Append the observed declaration/installation facts for one admitted query.

    Returns ``None`` when the caller's evaluation is not a real durable
    evaluation (a dependency double carries no observable runtime facts) or when
    the session is not an ``AsyncSession``.
    """
    if not isinstance(evaluation, MarketDataCapabilityEvaluation):
        return None
    if not isinstance(db, AsyncSession):
        return None
    observations = _observations(evaluation)
    if not observations:
        return AdmissionObservationResult(recorded_capability_ids=(), skipped_capability_ids=())

    now = _trusted_now(clock or _utc_now)
    horizon = now + observation_window
    if horizon <= now:
        return AdmissionObservationResult(recorded_capability_ids=(), skipped_capability_ids=())

    recorded: list[str] = []
    skipped: list[str] = []
    pending: list[MdCapabilityLedgerEntry] = []
    try:
        async with _WRITE_LOCK:
            existing = await _existing_rows(
                db, [observation.capability_id for observation in observations]
            )
            for observation in observations:
                entries = existing.get(observation.capability_id, ())
                if _already_recorded(entries, observation) or not _window_is_free(
                    entries, effective_from=now, effective_until=horizon
                ):
                    skipped.append(observation.capability_id)
                    continue
                next_revision = max((entry[0] for entry in entries), default=0) + 1
                pending.append(
                    MdCapabilityLedgerEntry(
                        capability_id=observation.capability_id,
                        revision=next_revision,
                        descriptor_sha256=observation.descriptor_sha256,
                        evidence_sha256=observation.evidence_sha256,
                        declared_capability=observation.declared,
                        installed_capability=observation.installed,
                        # Neither of these is observable from a request, so both
                        # stay unclaimed with NULL windows.
                        verified_capability=False,
                        verified_at=None,
                        verified_until=None,
                        authorized_capability=False,
                        authorized_at=None,
                        authorized_until=None,
                        effective_from=now,
                        effective_until=horizon,
                    )
                )
            if not pending:
                return AdmissionObservationResult(
                    recorded_capability_ids=(),
                    skipped_capability_ids=tuple(skipped),
                )
            db.add_all(pending)
            # The durable observation must survive the handler's own refusal:
            # ``get_db`` never commits a session that ends in an HTTPException.
            await db.commit()
        recorded = [str(entry.capability_id) for entry in pending]
    except IntegrityError:
        # Another worker appended the same pre-image first; the unique
        # (capability_id, revision) key is the idempotency tiebreak.
        await _safe_rollback(db)
        skipped = sorted({*skipped, *(str(entry.capability_id) for entry in pending)})
        recorded = []
    except SQLAlchemyError as exc:
        await _safe_rollback(db)
        logger.warning(
            "market-data capability admission observation skipped: %s",
            type(exc).__name__,
        )
        return AdmissionObservationResult(
            recorded_capability_ids=(),
            skipped_capability_ids=tuple(
                [observation.capability_id for observation in observations]
            ),
        )
    return AdmissionObservationResult(
        recorded_capability_ids=tuple(recorded),
        skipped_capability_ids=tuple(skipped),
    )


async def _safe_rollback(db: AsyncSession) -> None:
    """Roll back a failed observation write; a dead session has nothing to undo."""
    try:
        await db.rollback()
    except Exception:
        logger.warning("market-data capability admission rollback failed")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _trusted_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("capability admission clock must return an aware datetime")
    return value.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "ADMISSION_OBSERVATION_KIND",
    "ADMISSION_OBSERVATION_VERSION",
    "AdmissionObservation",
    "AdmissionObservationResult",
    "DEFAULT_OBSERVATION_WINDOW",
    "record_admission_observations",
]
