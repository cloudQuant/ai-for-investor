"""Registered AI-for-Investor consumers of the shared service packages.

This is the machine-checked form of the migration registry: every application
surface that reads or writes through a shared service is listed with the
capability it needs, the strongest evidence obtained for it so far, and its
migration status.  It is deliberately data, not a second engine: nothing here
performs a read or a write, and an unlisted surface must not be treated as
already migrated.

Evidence levels are ordered and must not be conflated:

``contract``
    Only the neutral contract and the offline checks exist.
``offline``
    The adapter is exercised against injected fakes with no service running.
``local-process``
    A real service process was started on this machine for the check.
``real-service``
    The deployed service answered over its real transport and authorization.

``pending`` means the surface still uses its legacy path; no application
surface may be reported as migrated without evidence at the level its
capability requires.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

__all__ = [
    "CONSUMERS",
    "ConsumerRegistryError",
    "EVIDENCE_LEVELS",
    "MIGRATION_STATUSES",
    "SERVICE_CAPABILITIES",
    "ServiceConsumer",
    "consumer_for",
    "validate_consumers",
]


class ConsumerRegistryError(ValueError):
    """The consumer registry is inconsistent or names an unknown capability."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


#: Capabilities an application surface may require, mirroring the service ports.
SERVICE_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "service.account_read",
        "service.monitor_query",
        "service.monitor_control",
        "service.risk_query",
        "service.risk_analysis",
        "service.risk_policy",
        "service.order_entry",
        "service.order_query",
        "service.order_group_entry",
    }
)

EVIDENCE_LEVELS: Final[tuple[str, ...]] = (
    "contract",
    "offline",
    "local-process",
    "real-service",
)

MIGRATION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "pending",
        "read-migrated",
        "write-migrated",
        "retired",
    }
)


@dataclass(frozen=True)
class ServiceConsumer:
    """One application surface and the service capability it must use."""

    consumer_id: str
    surface: str
    capability: str
    status: str
    evidence: str
    authority_owner: str
    notes: str

    def __post_init__(self) -> None:
        for value, code in (
            (self.consumer_id, "INVALID_CONSUMER_ID"),
            (self.surface, "INVALID_SURFACE"),
            (self.authority_owner, "INVALID_AUTHORITY_OWNER"),
        ):
            if type(value) is not str or not value or value != value.strip() or len(value) > 200:
                raise ConsumerRegistryError(code)
        if self.capability not in SERVICE_CAPABILITIES:
            raise ConsumerRegistryError("UNKNOWN_CAPABILITY")
        if self.status not in MIGRATION_STATUSES:
            raise ConsumerRegistryError("UNKNOWN_STATUS")
        if self.evidence not in EVIDENCE_LEVELS:
            raise ConsumerRegistryError("UNKNOWN_EVIDENCE")
        if self.status == "pending" and self.evidence != "contract":
            raise ConsumerRegistryError("PENDING_CONSUMER_MUST_BE_CONTRACT_ONLY")
        if self.status in {"read-migrated", "write-migrated"} and self.evidence == "contract":
            raise ConsumerRegistryError("MIGRATED_CONSUMER_REQUIRES_EVIDENCE")
        if type(self.notes) is not str or len(self.notes) > 400:
            raise ConsumerRegistryError("INVALID_NOTES")


#: The application surfaces named by the migration plan.  Every entry starts
#: from its recorded baseline; changing a status requires the matching evidence.
_CONSUMERS: Final[tuple[ServiceConsumer, ...]] = (
    ServiceConsumer(
        consumer_id="portfolio-overview",
        surface="GET /api/v1/portfolio/*",
        capability="service.account_read",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_gateway",
        notes=(
            "Live workspace aggregation still reads the application's own "
            "session state; the authorized account view adapter is not wired."
        ),
    ),
    ServiceConsumer(
        consumer_id="portfolio-ledger",
        surface="GET/POST /api/v1/portfolio/ledger/*",
        capability="service.account_read",
        status="pending",
        evidence="contract",
        authority_owner="ai-for-investor",
        notes=(
            "User-imported transaction rows stay application business data; "
            "they are never projected as provider account facts."
        ),
    ),
    ServiceConsumer(
        consumer_id="risk-analytics",
        surface="GET /api/v1/risk-analytics/*",
        capability="service.risk_analysis",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_risk",
        notes="Local kernels still compute; no analysis worker is deployed.",
    ),
    ServiceConsumer(
        consumer_id="risk-control-policy",
        surface="GET/POST /api/v1/risk-control/*",
        capability="service.risk_policy",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_risk",
        notes=(
            "In-process rule CRUD is not an admission decision and must not be presented as one."
        ),
    ),
    ServiceConsumer(
        consumer_id="manual-and-ai-orders",
        surface="live trading workspace order actions",
        capability="service.order_entry",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_execution",
        notes=(
            "DirectOrderService still dispatches through the legacy gateway "
            "bridge; the SDK execution client is not wired here yet."
        ),
    ),
    ServiceConsumer(
        consumer_id="paper-trading",
        surface="paper runtime order endpoints",
        capability="service.order_entry",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_execution",
        notes="Simulated matching and its ledger still live in the application.",
    ),
    ServiceConsumer(
        consumer_id="monitoring-alerts",
        surface="GET/POST /api/v1/monitoring/*",
        capability="service.monitor_query",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_monitor",
        notes=("Alert state is still evaluated in-process; no producer event stream is consumed."),
    ),
    ServiceConsumer(
        consumer_id="strategy-health",
        surface="workspace strategy status panels",
        capability="service.monitor_query",
        status="read-migrated",
        evidence="local-process",
        authority_owner="bt_api_monitor",
        notes=(
            "Strategy heartbeat/health projects from the authorized telemetry "
            "snapshot and was verified against a real local service process "
            "over CURVE: not_collected -> fresh -> stale -> unavailable. A "
            "missing heartbeat never infers health from order activity."
        ),
    ),
    ServiceConsumer(
        consumer_id="market-quotes",
        surface="GET /api/v1/realtime/*",
        capability="service.account_read",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_gateway",
        notes=(
            "QuoteService still owns a provider subscription; the shared "
            "market feed is not wired to the browser fan-out."
        ),
    ),
    ServiceConsumer(
        consumer_id="data-topics",
        surface="websocket /ws/data/*",
        capability="service.monitor_query",
        status="pending",
        evidence="contract",
        authority_owner="bt_api_monitor",
        notes="Browser push remains a presentation adapter over application state.",
    ),
)

#: Immutable view of the registry for callers that must not mutate it.
CONSUMERS: Final[MappingProxyType[str, ServiceConsumer]] = MappingProxyType(
    {consumer.consumer_id: consumer for consumer in _CONSUMERS}
)


def consumer_for(consumer_id: str) -> ServiceConsumer:
    """Return one registered consumer or fail with a finite code."""

    if type(consumer_id) is not str or consumer_id not in CONSUMERS:
        raise ConsumerRegistryError("UNKNOWN_CONSUMER")
    return CONSUMERS[consumer_id]


def validate_consumers() -> tuple[ServiceConsumer, ...]:
    """Return the registry after checking that it is internally consistent."""

    if len(CONSUMERS) != len(_CONSUMERS):
        raise ConsumerRegistryError("DUPLICATE_CONSUMER_ID")
    surfaces = [consumer.surface for consumer in _CONSUMERS]
    if len(set(surfaces)) != len(surfaces):
        raise ConsumerRegistryError("DUPLICATE_SURFACE")
    for consumer in _CONSUMERS:
        if not consumer.notes:
            raise ConsumerRegistryError("MISSING_NOTES")
    return _CONSUMERS
