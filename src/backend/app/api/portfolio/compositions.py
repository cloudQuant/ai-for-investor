"""Authenticated API for immutable portfolio composition versions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.service_read import _resolve_access
from app.db.database import get_db
from app.schemas.auth import TokenPayload
from app.schemas.portfolio_composition import PortfolioCompositionCreate
from app.services.portfolio_composition import PortfolioCompositionService

router = APIRouter(prefix="/portfolio/compositions", tags=["Portfolio Compositions"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_portfolio_composition_version(
    payload: PortfolioCompositionCreate,
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Write a new membership version; owner identity is taken from the JWT."""

    if payload.source_type == "live":
        for member in payload.members:
            if member.kind == "account":
                _resolve_access(current_user, member.ref, "account")
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
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Read one source-aware, display-only projection of exact membership."""

    service = PortfolioCompositionService(db)
    row = await service.get_version(current_user.sub, portfolio_ref, membership_version)
    return await service.project(current_user, row)


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
