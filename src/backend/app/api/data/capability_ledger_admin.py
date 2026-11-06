"""Admin-only durable attestation surface for the market-data capability ledger.

The v2 data plane is fail-closed until this ledger holds one current record per
reviewed capability.  Nothing in the application could previously append such a
record, so the durable gate could only ever read ``CAPABILITY_LEDGER_MISSING``.
These endpoints give an authenticated operator that ability without giving
them the ability to choose the hashes the gate checks: the descriptor and
evidence digests are always derived by the service from the live reviewed
policy and the persisted receipt plane.

Authorization is the existing data-admin boundary (``require_data_admin_user``)
and every append writes the shared audit trail with the operator's user ID plus
the derived receipt.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.data.deps import require_data_admin_user
from app.api.data.queries import evaluate_market_data_capabilities
from app.db.database import get_db
from app.models.user import User
from app.schemas.market_data_capability_ledger import (
    MarketDataCapabilityEvidenceResponse,
    MarketDataCapabilityEvidenceRouteResponse,
    MarketDataCapabilityLedgerReceiptResponse,
    MarketDataCapabilityLedgerRecordRequest,
)
from app.services.market_data.capability_ledger import route_capability_id
from app.services.market_data.capability_ledger_admin import (
    CapabilityEvidenceSummary,
    CapabilityLedgerAdminError,
    MarketDataCapabilityLedgerAdminService,
)
from app.services.market_data.source_policy import MarketDataSourcePolicy

router = APIRouter(
    prefix="/data/market-data/capability-ledger",
    tags=["Market Data Capability Ledger"],
)

_REVIEWED_SOURCE_POLICY_ID = "market-default-v1"

_ERROR_STATUS: dict[str, int] = {
    "CAPABILITY_LEDGER_ADMIN_ROUTE_UNDECLARED": status.HTTP_404_NOT_FOUND,
    "CAPABILITY_LEDGER_ADMIN_CAPABILITY_UNKNOWN": status.HTTP_404_NOT_FOUND,
    "CAPABILITY_LEDGER_ADMIN_RECORD_MISSING": status.HTTP_404_NOT_FOUND,
    "CAPABILITY_LEDGER_ADMIN_ACTOR_UNKNOWN": status.HTTP_404_NOT_FOUND,
    "CAPABILITY_LEDGER_ADMIN_ACTOR_DISABLED": status.HTTP_403_FORBIDDEN,
    "CAPABILITY_LEDGER_ADMIN_WINDOW_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "CAPABILITY_LEDGER_ADMIN_STAGE_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "CAPABILITY_LEDGER_ADMIN_REVISION_INVALID": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "CAPABILITY_LEDGER_ADMIN_VERIFICATION_WINDOW": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "CAPABILITY_LEDGER_ADMIN_AUTHORIZATION_WINDOW": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "CAPABILITY_LEDGER_ADMIN_WINDOW_OVERLAP": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_PRIOR_UNBOUNDED": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_NOT_DECLARED": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_NOT_INSTALLED": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_NOT_VERIFIED": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_VERIFICATION_LAPSED": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_EVIDENCE_MISSING": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_EVIDENCE_UNBOUNDED": status.HTTP_409_CONFLICT,
    "CAPABILITY_LEDGER_ADMIN_EVIDENCE_INTEGRITY": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


def get_market_data_capability_ledger_admin_service(
    db: AsyncSession = Depends(get_db),
) -> MarketDataCapabilityLedgerAdminService:
    """Build the request-scoped durable attestation writer."""
    return MarketDataCapabilityLedgerAdminService(db)


async def require_market_data_capability_ledger_admin(
    current_user: User = Depends(require_data_admin_user),
) -> User:
    """Reuse the existing data-admin boundary and expose the verified principal.

    ``require_data_admin_user`` already enforces authentication plus the ADMIN
    role; nothing here narrows that check.  The returned principal is what the
    service records as the authorizing operator.
    """
    return current_user


async def get_reviewed_market_data_source_policy(
    db: AsyncSession = Depends(get_db),
) -> MarketDataSourcePolicy:
    """Return the reviewed route set this build ships, as the reader resolves it.

    The durable evaluator keeps every reviewed route in its effective policy, so
    an attestation can only ever describe a route the server actually owns.
    """
    evaluation = await evaluate_market_data_capabilities(db)
    return evaluation.effective_source_policies.resolve(_REVIEWED_SOURCE_POLICY_ID)


def _evidence_response(summary: CapabilityEvidenceSummary) -> MarketDataCapabilityEvidenceResponse:
    return MarketDataCapabilityEvidenceResponse(
        capability_id=summary.capability_id,
        descriptor_sha256=summary.descriptor_sha256,
        evidence_kind=summary.evidence_kind,
        evidence_sha256=summary.evidence_sha256,
        artifact_count=summary.artifact_count,
        window_end=summary.window_end,
        routes=tuple(
            MarketDataCapabilityEvidenceRouteResponse(
                capability_id=str(item["capability_id"]),
                route_id=str(item["route_id"]),
                artifact_count=int(item["artifact_count"]),
            )
            for item in summary.routes
        ),
        matches_stored=summary.matches_stored,
        reason_code=summary.reason_code,
    )


def _raise_http_error(exc: CapabilityLedgerAdminError) -> None:
    detail: dict[str, Any] = {"code": exc.code}
    detail.update(exc.detail)
    raise HTTPException(
        status_code=_ERROR_STATUS.get(exc.code, status.HTTP_409_CONFLICT),
        detail=detail,
    ) from exc


@router.post(
    "/records",
    status_code=status.HTTP_201_CREATED,
    response_model=MarketDataCapabilityLedgerReceiptResponse,
    summary="Append one durable market-data capability attestation revision",
)
async def append_market_data_capability_ledger_record(
    payload: MarketDataCapabilityLedgerRecordRequest,
    operator: User = Depends(require_market_data_capability_ledger_admin),
    policy: MarketDataSourcePolicy = Depends(get_reviewed_market_data_source_policy),
    service: MarketDataCapabilityLedgerAdminService = Depends(
        get_market_data_capability_ledger_admin_service
    ),
) -> MarketDataCapabilityLedgerReceiptResponse:
    """Append one lifecycle revision after deriving both digests server-side."""
    try:
        receipt = await service.append_record(
            capability_id=payload.capability_id,
            stage=payload.stage,
            policy=policy,
            actor_user_id=str(operator.id),
            effective_until=payload.effective_until,
            effective_from=payload.effective_from,
            verified_until=payload.verified_until,
            authorized_until=payload.authorized_until,
        )
    except CapabilityLedgerAdminError as exc:
        _raise_http_error(exc)
    return MarketDataCapabilityLedgerReceiptResponse(
        ledger_record_id=receipt.ledger_record_id,
        capability_id=receipt.capability_id,
        revision=receipt.revision,
        stage=receipt.stage,
        descriptor_sha256=receipt.descriptor_sha256,
        evidence_sha256=receipt.evidence_sha256,
        evidence_kind=receipt.evidence_kind,
        artifact_count=receipt.artifact_count,
        declared_capability=receipt.declared_capability,
        installed_capability=receipt.installed_capability,
        verified_capability=receipt.verified_capability,
        authorized_capability=receipt.authorized_capability,
        effective_from=receipt.effective_from,
        effective_until=receipt.effective_until,
        verified_at=receipt.verified_at,
        verified_until=receipt.verified_until,
        authorized_at=receipt.authorized_at,
        authorized_until=receipt.authorized_until,
        actor_user_id=receipt.actor_user_id,
        receipt_sha256=receipt.receipt_sha256,
    )


@router.get(
    "/records/{capability_id}/evidence",
    response_model=MarketDataCapabilityEvidenceResponse,
    summary="Preview or re-verify one capability's durable evidence plane",
)
async def read_market_data_capability_evidence(
    capability_id: str,
    revision: int | None = Query(default=None, ge=1),
    window_end: datetime | None = Query(default=None),
    operator: User = Depends(require_market_data_capability_ledger_admin),
    policy: MarketDataSourcePolicy = Depends(get_reviewed_market_data_source_policy),
    service: MarketDataCapabilityLedgerAdminService = Depends(
        get_market_data_capability_ledger_admin_service
    ),
) -> MarketDataCapabilityEvidenceResponse:
    """Return the digest the server would derive, without writing anything."""
    try:
        if revision is None:
            summary = await service.preview_evidence(
                capability_id=capability_id,
                policy=policy,
                window_end=window_end,
            )
        else:
            summary = await service.reverify_record(
                capability_id=capability_id,
                revision=revision,
                policy=policy,
            )
    except CapabilityLedgerAdminError as exc:
        _raise_http_error(exc)
    return _evidence_response(summary)


@router.get(
    "/effective",
    response_model=None,
    summary="Read back the effective capability state the durable ledger grants",
)
async def read_market_data_capability_effective_state(
    operator: User = Depends(require_market_data_capability_ledger_admin),
    policy: MarketDataSourcePolicy = Depends(get_reviewed_market_data_source_policy),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the reader's own verdict so an operator can confirm an append took."""
    evaluation = await evaluate_market_data_capabilities(db)
    return {
        "query_v2_enabled": evaluation.response.query_v2_enabled,
        "online_fetch_enabled": evaluation.response.online_fetch_enabled,
        "research_cache_fill_enabled": evaluation.response.research_cache_fill_enabled,
        "research_backtest_bridge_enabled": evaluation.response.research_backtest_bridge_enabled,
        "effective_route_ids": sorted(evaluation.effective_route_ids),
        "reviewed_route_capability_ids": sorted(
            route_capability_id(route.route_id) for route in policy.routes
        ),
    }
