from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.mysql import get_db
from app.models.user import User
from app.models.preference import UserPreference
from app.schemas.preference import UserPreferenceUpdate, UserPreferenceResponse

router = APIRouter()
SUPPORTED_UI_THEMES = {
    "fintech-trust-light",
    "terminal-agent-dark",
    "minimal-focus",
    "research-docs-light",
}


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    from jose import jwt
    from app.core.config import settings

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None

    token = auth.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if user_id:
            result = await db.execute(select(User).where(User.id == int(user_id)))
            return result.scalar_one_or_none()
    except Exception:
        pass
    return None


@router.get("/me/preferences")
async def get_preferences(request: Request, db: AsyncSession = Depends(get_db)):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)

    if not current_user:
        return {"data": {"ui_theme": "fintech-trust-light"}, "request_id": request_id}

    # Explicitly query preferences to avoid lazy loading issues in async context
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = pref_result.scalar_one_or_none()

    if pref:
        return {
            "data": {
                "id": pref.id,
                "user_id": pref.user_id,
                "ui_theme": pref.ui_theme,
                "system_theme_sync": bool(pref.system_theme_sync),
            },
            "request_id": request_id,
        }

    return {
        "data": {"user_id": current_user.id, "ui_theme": "fintech-trust-light", "system_theme_sync": False},
        "request_id": request_id,
    }


@router.patch("/me/preferences")
async def update_preferences(
    request: Request,
    data: UserPreferenceUpdate,
    db: AsyncSession = Depends(get_db),
):
    request_id = getattr(request.state, "request_id", None)
    current_user = await get_current_user(request, db)

    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")

    if data.ui_theme is not None and data.ui_theme not in SUPPORTED_UI_THEMES:
        raise HTTPException(status_code=400, detail="Unsupported UI theme")

    # Explicitly query preferences to avoid lazy loading issues
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    pref = pref_result.scalar_one_or_none()

    if pref:
        if data.ui_theme is not None:
            pref.ui_theme = data.ui_theme
        if data.system_theme_sync is not None:
            pref.system_theme_sync = int(data.system_theme_sync)
    else:
        pref = UserPreference(
            user_id=current_user.id,
            ui_theme=data.ui_theme or "fintech-trust-light",
            system_theme_sync=int(data.system_theme_sync) if data.system_theme_sync is not None else 0,
        )
        db.add(pref)

    await db.commit()

    return {
        "data": {
            "id": pref.id,
            "user_id": pref.user_id,
            "ui_theme": pref.ui_theme,
            "system_theme_sync": bool(pref.system_theme_sync),
        },
        "request_id": request_id,
    }
