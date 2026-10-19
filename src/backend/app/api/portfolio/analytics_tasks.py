"""Authenticated AFI routes for the existing Risk portfolio task service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.portfolio_analytics_v1 import (
    PortfolioAnalyticsDatasetCreateV1,
    PortfolioAnalyticsTaskCreateV1,
)
from app.schemas.portfolio_analytics_tasks import PortfolioAnalyticsTaskCreate
from app.services.portfolio_analytics_datasets_v1 import (
    PortfolioAnalyticsDatasetV1Error,
    PortfolioAnalyticsDatasetV1Service,
)
from app.services.portfolio_analytics_tasks import (
    PortfolioAnalyticsTaskError,
    PortfolioAnalyticsTaskService,
)
from app.services.portfolio_analytics_v1_tasks import (
    PortfolioAnalyticsV1TaskError,
    PortfolioAnalyticsV1TaskService,
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


@router.post(
    "/{portfolio_ref}/versions/{membership_version}/analytics-v1-datasets",
    status_code=status.HTTP_201_CREATED,
)
async def create_portfolio_analytics_v1_dataset(
    portfolio_ref: str,
    membership_version: int,
    payload: PortfolioAnalyticsDatasetCreateV1,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist caller-supplied facts as immutable offline data for one owned cut."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    try:
        return await PortfolioAnalyticsDatasetV1Service(db).create(
            current_user.sub, membership, payload
        )
    except PortfolioAnalyticsDatasetV1Error as error:
        raise _analytics_v1_error(error) from None


@router.get(
    "/{portfolio_ref}/versions/{membership_version}/analytics-v1-datasets/{dataset_ref}"
)
async def get_portfolio_analytics_v1_dataset(
    portfolio_ref: str,
    membership_version: int,
    dataset_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return traceable metadata for a dataset owned by this subject and cut."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    try:
        row, _facts = await PortfolioAnalyticsDatasetV1Service(db).get_owned(
            current_user.sub, membership, dataset_ref
        )
        return PortfolioAnalyticsDatasetV1Service._metadata(row)
    except PortfolioAnalyticsDatasetV1Error as error:
        raise _analytics_v1_error(error) from None


@router.post(
    "/{portfolio_ref}/versions/{membership_version}/analytics-v1-tasks",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_portfolio_analytics_v1_task(
    portfolio_ref: str,
    membership_version: int,
    payload: PortfolioAnalyticsTaskCreateV1,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Submit an immutable stored dataset through the configured Risk owner."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    task_service = _bound_v1_task_service(current_user, portfolio_ref, membership)
    try:
        dataset, facts = await PortfolioAnalyticsDatasetV1Service(db).get_owned(
            current_user.sub, membership, payload.dataset_ref
        )
        return await task_service.create(dataset, facts, payload)
    except PortfolioAnalyticsDatasetV1Error as error:
        raise _analytics_v1_error(error) from None
    except PortfolioAnalyticsV1TaskError as error:
        raise _analytics_v1_error(error) from None


@router.get(
    "/{portfolio_ref}/versions/{membership_version}/analytics-v1-tasks/{task_ref}"
)
async def query_portfolio_analytics_v1_task(
    portfolio_ref: str,
    membership_version: int,
    task_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Read only a V1 task attached to an owned immutable dataset."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    task_service = _bound_v1_task_service(current_user, portfolio_ref, membership)
    try:
        dataset_ref = task_service.dataset_ref_for_task(task_ref)
        dataset, facts = await PortfolioAnalyticsDatasetV1Service(db).get_owned(
            current_user.sub, membership, dataset_ref
        )
        return await task_service.query(dataset, facts, task_ref)
    except PortfolioAnalyticsDatasetV1Error as error:
        raise _analytics_v1_error(error) from None
    except PortfolioAnalyticsV1TaskError as error:
        raise _analytics_v1_error(error) from None


@router.post(
    "/{portfolio_ref}/versions/{membership_version}/analytics-v1-tasks/{task_ref}/cancel"
)
async def cancel_portfolio_analytics_v1_task(
    portfolio_ref: str,
    membership_version: int,
    task_ref: str,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Cancel a V1 task through the same configured Risk owner."""

    membership = await _owned_membership(db, current_user, portfolio_ref, membership_version)
    task_service = _bound_v1_task_service(current_user, portfolio_ref, membership)
    try:
        dataset_ref = task_service.dataset_ref_for_task(task_ref)
        dataset, facts = await PortfolioAnalyticsDatasetV1Service(db).get_owned(
            current_user.sub, membership, dataset_ref
        )
        return await task_service.cancel(dataset, facts, task_ref)
    except PortfolioAnalyticsDatasetV1Error as error:
        raise _analytics_v1_error(error) from None
    except PortfolioAnalyticsV1TaskError as error:
        raise _analytics_v1_error(error) from None


def _bound_v1_task_service(
    current_user: TokenPayload,
    portfolio_ref: str,
    membership: Any,
) -> PortfolioAnalyticsV1TaskService:
    if membership.source_type not in {"research", "imported", "paper"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ANALYTICS_OFFLINE_SOURCE_REQUIRED"},
        )
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
    worker = getattr(access, "worker", None)
    if (
        getattr(binding, "portfolio_ref", None) != portfolio_ref
        or getattr(binding, "mount", None) != "application.risk_analysis"
        or type(getattr(binding, "scope_ref", None)) is not str
        or not getattr(binding, "scope_ref", None)
        or worker is None
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "ANALYTICS_SERVICE_NOT_CONFIGURED"},
        )
    try:
        return PortfolioAnalyticsV1TaskService(
            worker,
            scope_ref=binding.scope_ref,
            owner_subject=current_user.sub,
            membership=membership,
        )
    except PortfolioAnalyticsV1TaskError as error:
        raise _analytics_v1_error(error) from None


def _analytics_v1_error(error: PortfolioAnalyticsDatasetV1Error | PortfolioAnalyticsV1TaskError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": "The analytics dataset or task could not be completed."},
    )
