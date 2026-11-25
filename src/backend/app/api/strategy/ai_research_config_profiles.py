"""Owner-scoped AI research configuration profile routes."""

from __future__ import annotations

import typing
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.permission import Role, user_roles
from app.schemas.ai_strategy_research import (
    AIStrategyResearchConfigProfile,
    AIStrategyResearchConfigProfileCreate,
    AIStrategyResearchConfigProfileImportRequest,
    AIStrategyResearchConfigProfileImportResponse,
    AIStrategyResearchConfigProfileListResponse,
    AIStrategyResearchConfigProfileUpdate,
)
from app.services.ai_strategy_research_config_profiles import AIStrategyResearchConfigProfileService

router = APIRouter()


@lru_cache
def get_ai_strategy_research_config_profiles() -> typing.Any:
    return AIStrategyResearchConfigProfileService()


async def _can_manage_global_config_profiles(current_user: typing.Any, db: AsyncSession) -> bool:
    result = await db.execute(
        select(user_roles.c.role).where(
            user_roles.c.user_id == current_user.sub,
            user_roles.c.role == Role.ADMIN.value,
        )
    )
    return result.scalar_one_or_none() is not None


@router.get(
    "/ai-research/config-profiles",
    response_model=AIStrategyResearchConfigProfileListResponse,
    summary="List local AI strategy research configuration profiles",
)
async def list_ai_strategy_research_config_profiles(
    current_user: typing.Any = Depends(get_current_user),
    service: AIStrategyResearchConfigProfileService = Depends(
        get_ai_strategy_research_config_profiles
    ),
) -> typing.Any:
    try:
        return await service.list_profiles(current_user.sub)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/ai-research/config-profiles",
    response_model=AIStrategyResearchConfigProfile,
    status_code=status.HTTP_201_CREATED,
    summary="Create a local AI strategy research configuration profile",
)
async def create_ai_strategy_research_config_profile(
    data: AIStrategyResearchConfigProfileCreate,
    current_user: typing.Any = Depends(get_current_user),
    service: AIStrategyResearchConfigProfileService = Depends(
        get_ai_strategy_research_config_profiles
    ),
) -> typing.Any:
    try:
        return await service.create_profile(data, owner_id=current_user.sub)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/ai-research/config-profiles/import",
    response_model=AIStrategyResearchConfigProfileImportResponse,
    summary="Import AI strategy research configuration profiles from YAML",
)
async def import_ai_strategy_research_config_profiles(
    data: AIStrategyResearchConfigProfileImportRequest,
    current_user: typing.Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AIStrategyResearchConfigProfileService = Depends(
        get_ai_strategy_research_config_profiles
    ),
) -> typing.Any:
    try:
        return await service.import_profiles(
            data.raw_yaml,
            fallback_name=data.name,
            fallback_profile_id=data.profile_id,
            owner_id=current_user.sub,
            can_manage_global=await _can_manage_global_config_profiles(current_user, db),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/ai-research/config-profiles/{profile_id}",
    response_model=AIStrategyResearchConfigProfile,
    summary="Get a local AI strategy research configuration profile",
)
async def get_ai_strategy_research_config_profile(
    profile_id: str,
    current_user: typing.Any = Depends(get_current_user),
    service: AIStrategyResearchConfigProfileService = Depends(
        get_ai_strategy_research_config_profiles
    ),
) -> typing.Any:
    try:
        profile = await service.get_profile(profile_id, current_user.sub)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI research config profile not found"
        )
    return profile


@router.put(
    "/ai-research/config-profiles/{profile_id}",
    response_model=AIStrategyResearchConfigProfile,
    summary="Update a local AI strategy research configuration profile",
)
async def update_ai_strategy_research_config_profile(
    profile_id: str,
    data: AIStrategyResearchConfigProfileUpdate,
    current_user: typing.Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AIStrategyResearchConfigProfileService = Depends(
        get_ai_strategy_research_config_profiles
    ),
) -> typing.Any:
    try:
        profile = await service.update_profile(
            profile_id,
            data,
            current_user.sub,
            can_manage_global=await _can_manage_global_config_profiles(current_user, db),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI research config profile not found"
        )
    return profile


@router.delete(
    "/ai-research/config-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a local AI strategy research configuration profile",
    response_model=None,
)
async def delete_ai_strategy_research_config_profile(
    profile_id: str,
    current_user: typing.Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: AIStrategyResearchConfigProfileService = Depends(
        get_ai_strategy_research_config_profiles
    ),
) -> typing.Any:
    try:
        deleted = await service.delete_profile(
            profile_id,
            current_user.sub,
            can_manage_global=await _can_manage_global_config_profiles(current_user, db),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="AI research config profile not found"
        )
