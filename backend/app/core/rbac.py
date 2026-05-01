from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import Role, User, UserRoleEnum


ADMIN_ROLES = {UserRoleEnum.ADMIN.value}
MODERATION_ROLES = {UserRoleEnum.MODERATOR.value, UserRoleEnum.ADMIN.value}
CONTENT_ROLES = {UserRoleEnum.AUTHOR.value, UserRoleEnum.EDITOR.value, UserRoleEnum.ADMIN.value}


def user_role_names(user: User) -> set[str]:
    return {role.name for role in getattr(user, "roles", [])}


def require_roles(user: User | None, allowed_roles: set[str]) -> None:
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    if user_role_names(user).isdisjoint(allowed_roles):
        raise HTTPException(status_code=403, detail="Insufficient role")


def require_admin_user(user: User | None) -> None:
    require_roles(user, ADMIN_ROLES)


def require_moderator_user(user: User | None) -> None:
    require_roles(user, MODERATION_ROLES)


def require_content_user(user: User | None) -> None:
    require_roles(user, CONTENT_ROLES)


async def bootstrap_initial_admin(db: AsyncSession, email: str, username: str, password: str) -> User:
    existing_admin_result = await db.execute(select(User).join(User.roles).where(Role.name == UserRoleEnum.ADMIN.value))
    if existing_admin_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Administrator already exists")

    existing_user_result = await db.execute(select(User).where(User.email == email))
    if existing_user_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    role_result = await db.execute(select(Role).where(Role.name == UserRoleEnum.ADMIN.value))
    admin_role = role_result.scalar_one_or_none()
    if admin_role is None:
        admin_role = Role(name=UserRoleEnum.ADMIN.value, description="Administrator")
        db.add(admin_role)

    admin_user = User(
        email=email,
        username=username,
        password_hash=hash_password(password),
        email_verified_at=datetime.now(timezone.utc),
        is_active=True,
    )
    admin_user.roles.append(admin_role)
    db.add(admin_user)
    await db.commit()
    await db.refresh(admin_user)
    return admin_user
