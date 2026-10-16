"""Authenticated AFI routes for the existing Risk portfolio task service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.portfolio_analytics_tasks import PortfolioAnalyticsTaskCreate
from app.services.portfolio_analytics_tasks import (
    PortfolioAnalyticsTaskError,
    PortfolioAnalyticsTaskService,
)
from app.services.portfolio_composition import PortfolioCompositionService

router = APIRouter(prefix="/portfolio/compositions", tags=["Portfolio Analytics Tasks"])


@router.post(
    "/{portfolio_ref}/versions/{membership_version}/analytics-tasks",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_portfolio_analytics_task(
    portfolio_ref: str,
    membership_version: int,
    payload: PortfolioAnalyticsTaskCreate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist one offline V2 fact cut and submit its version-bound task."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    service = _bound_task_service(current_user, portfolio_ref, membership)
    try:
        return await service.create(payload)
    except PortfolioAnalyticsTaskError as error:
        raise _task_error(error) from None


@router.get(
    "/{portfolio_ref}/versions/{membership_version}/analytics-tasks/{task_ref}"
)
async def query_portfolio_analytics_task(
    portfolio_ref: str,
    membership_version: int,
    task_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Read only a task attached to this subject's selected immutable version."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    service = _bound_task_service(current_user, portfolio_ref, membership)
    try:
        return await service.query(task_ref)
    except PortfolioAnalyticsTaskError as error:
        raise _task_error(error) from None


@router.post(
    "/{portfolio_ref}/versions/{membership_version}/analytics-tasks/{task_ref}/cancel"
)
async def cancel_portfolio_analytics_task(
    portfolio_ref: str,
    membership_version: int,
    task_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel the pending task through the same configured Risk owner."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    service = _bound_task_service(current_user, portfolio_ref, membership)
    try:
        return await service.cancel(task_ref)
    except PortfolioAnalyticsTaskError as error:
        raise _task_error(error) from None


async def _owned_membership(
    db: AsyncSession,
    current_user: TokenPayload,
    portfolio_ref: str,
    membership_version: int,
):
    if membership_version < 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PORTFOLIO_COMPOSITION_NOT_FOUND"},
        )
    return await PortfolioCompositionService(db).get_version(
        current_user.sub, portfolio_ref, membership_version
    )


def _bound_task_service(
    current_user: TokenPayload,
    portfolio_ref: str,
    membership: Any,
) -> PortfolioAnalyticsTaskService:
    if membership.source_type not in {"research", "imported", "paper"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ANALYTICS_OFFLINE_SOURCE_REQUIRED"},
        )

    # This resolver is added to the shared service-read access directory by
    # the coordinated patch. It maps verified JWT subject + portfolio ref to
    # one server-configured binding; no scope selector comes from the request.
    import app.api.service_read as service_read_api

    resolver = getattr(service_read_api, "resolve_portfolio_analytics_access", None)
    if not callable(resolver):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ANALYTICS_SERVICE_NOT_CONFIGURED"},
        )
    try:
        access = resolver(current_user, portfolio_ref)
    except HTTPException:
        raise
    bindings = getattr(access, "portfolio_analytics_bindings", None)
    if not isinstance(bindings, Mapping):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ANALYTICS_SERVICE_NOT_CONFIGURED"},
        )
    binding = bindings.get(portfolio_ref)
    mount = getattr(binding, "mount", None)
    scope_ref = getattr(binding, "scope_ref", None)
    bound_portfolio_ref = getattr(binding, "portfolio_ref", None)
    worker = getattr(access, "worker", None)
    if (
        bound_portfolio_ref != portfolio_ref
        or mount != "application.risk_analysis"
        or type(scope_ref) is not str
        or not scope_ref
        or worker is None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ANALYTICS_SERVICE_NOT_CONFIGURED"},
        )
    try:
        return PortfolioAnalyticsTaskService(
            worker,
            scope_ref=scope_ref,
            owner_subject=current_user.sub,
            membership=membership,
        )
    except PortfolioAnalyticsTaskError as error:
        raise _task_error(error) from None


def _task_error(error: PortfolioAnalyticsTaskError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": "The analytics task could not be completed."},
    )
