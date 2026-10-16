"""Authenticated API for immutable portfolio composition versions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.service_read import _resolve_access
from app.db.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.portfolio_composition import PortfolioCompositionCreate
from app.services.portfolio_composition import PortfolioCompositionService
from app.services.portfolio_valuation_bindings import (
    PortfolioValuationBindingRegistry,
    attach_market_valuation_inputs,
)

router = APIRouter(prefix="/portfolio/compositions", tags=["Portfolio Compositions"])


@router.get("")
async def list_portfolio_composition_versions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List this authenticated owner's version selector metadata only."""

    rows, total = await PortfolioCompositionService(db).list_versions(
        current_user.sub, page, page_size
    )
    items = [
        {
            "portfolio_ref": row.portfolio_ref,
            "membership_version": row.membership_version,
            "source_type": row.source_type,
            "base_currency": row.base_currency,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": page * page_size < total,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_portfolio_composition_version(
    payload: PortfolioCompositionCreate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Write a new membership version; owner identity is taken from the JWT."""

    if payload.source_type == "live":
        account_members = {member.ref for member in payload.members if member.kind == "account"}
        subject_access = None
        for member in payload.members:
            if member.kind == "account":
                subject_access = _resolve_access(current_user, member.ref, "account_member")
        strategy_members = [member for member in payload.members if member.kind == "strategy"]
        if strategy_members and subject_access is None:
            # A strategy selector is not authority by itself. A live strategy
            # composition must also name an authorized account member.
            subject_access = _resolve_access(current_user, strategy_members[0].ref, "strategy_book")
        if subject_access is not None:
            for member in strategy_members:
                binding = subject_access.strategy_book_bindings.get(member.ref)
                if binding is None:
                    # A new live membership must bind every strategy selector
                    # to this authenticated subject's deployment-owned scope.
                    # Historical unbound versions remain readable and project
                    # attribution as unavailable.
                    subject_access = _resolve_access(
                        current_user, member.ref, "strategy_book"
                    )
                    binding = subject_access.strategy_book_bindings[member.ref]
                if binding.account_ref not in account_members:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail={"code": "SERVICE_READ_ACCESS_DENIED"},
                    )
                _resolve_access(current_user, binding.account_ref, "account_book")
    row = await PortfolioCompositionService(db).create_version(current_user.sub, payload)
    return _membership_payload(row)


@router.get("/{portfolio_ref}/versions/{membership_version}")
async def read_portfolio_composition_version(
    portfolio_ref: str,
    membership_version: int,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Read immutable owner-scoped membership metadata without account facts."""

    row = await PortfolioCompositionService(db).get_version(
        current_user.sub, portfolio_ref, membership_version
    )
    return _membership_payload(row)


@router.get("/{portfolio_ref}/versions/{membership_version}/projection")
async def read_portfolio_composition_projection(
    portfolio_ref: str,
    membership_version: int,
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Read one source-aware, display-only projection of exact membership."""

    service = PortfolioCompositionService(db)
    row = await service.get_version(current_user.sub, portfolio_ref, membership_version)
    projection = await service.project(current_user, row)
    if row.source_type != "live":
        return projection
    registry = getattr(request.app.state, "portfolio_valuation_bindings", None)
    if type(registry) is not PortfolioValuationBindingRegistry:
        registry = PortfolioValuationBindingRegistry.from_json(None)
    return await attach_market_valuation_inputs(
        projection,
        registry=registry,
        current_user=current_user,
        db=db,
    )


def _membership_payload(row: Any) -> dict[str, Any]:
    return {
        "portfolio_ref": row.portfolio_ref,
        "membership_version": row.membership_version,
        "membership_sha256": row.membership_sha256,
        "source_type": row.source_type,
        "base_currency": row.base_currency,
        "members": list(row.members),
        "projection_kind": "display_only",
        "creditable": False,
    }
