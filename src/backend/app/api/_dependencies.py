"""
API dependencies.
"""

import logging
import typing

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.permission import ROLE_PERMISSIONS, Permission, Role, user_roles
from app.models.user import User
from app.schemas.auth import TokenPayload
from app.utils.security import decode_access_token

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)
WEBSOCKET_TOKEN_PROTOCOL = "access-token"


def _extract_websocket_token(websocket: WebSocket) -> tuple[str | None, str | None]:
    protocols = websocket.headers.get("sec-websocket-protocol", "")
    offered = [item.strip() for item in protocols.split(",") if item.strip()]
    if len(offered) >= 2 and offered[0] == WEBSOCKET_TOKEN_PROTOCOL and offered[1]:
        return offered[1], WEBSOCKET_TOKEN_PROTOCOL
    return None, None


def get_websocket_current_user(websocket: WebSocket) -> tuple[TokenPayload | None, str | None]:
    token, accepted_subprotocol = _extract_websocket_token(websocket)
    if not token:
        return None, accepted_subprotocol

    payload = decode_access_token(token)
    if payload is None:
        return None, accepted_subprotocol

    return TokenPayload(**payload), accepted_subprotocol


async def get_current_user(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> TokenPayload:
    """Return the current authenticated user.

    Args:
        credentials: The HTTP authorization credentials.

    Returns:
        The token payload containing user information.

    Raises:
        HTTPException: If authentication credentials are invalid or missing.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_user = TokenPayload(**payload)
    request.state.user_id = current_user.sub
    return current_user


async def get_current_user_optional(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(HTTPBearer(auto_error=False)),
) -> TokenPayload | None:
    """Optionally return the current user (None if not authenticated).

    Args:
        credentials: Optional HTTP authorization credentials.

    Returns:
        The token payload if authenticated, None otherwise.
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        return None

    current_user = TokenPayload(**payload)
    request.state.user_id = current_user.sub
    return current_user


def _compatibility_role_values(user: object) -> list[object] | None:
    """Read legacy in-memory role assignments when a caller supplies them."""
    attached_roles: object = getattr(user, "roles", None)
    if not isinstance(attached_roles, (list, tuple)):
        return None

    role_values: list[object] = []
    for assignment in attached_roles:
        role_value: object = getattr(assignment, "role", assignment)
        role_values.append(role_value)
    return role_values


def _roles_grant_permission(role_values: list[object], permission: Permission) -> bool:
    user_permissions: list[Permission] = []
    for role_value in role_values:
        try:
            role = Role(role_value)
        except (TypeError, ValueError):
            continue
        user_permissions.extend(ROLE_PERMISSIONS.get(role, []))
    return permission in user_permissions


async def _database_role_values(db: AsyncSession, user_id: str) -> list[object]:
    result = await db.execute(select(user_roles.c.role).where(user_roles.c.user_id == user_id))
    role_values: list[object] = []
    for role_value in result.scalars().all():
        if isinstance(role_value, (str, Role)):
            role_values.append(role_value)
    return role_values


async def _effective_role_values(user: TokenPayload, db: AsyncSession) -> list[object]:
    role_values = _compatibility_role_values(user)
    if role_values is None:
        role_values = await _database_role_values(db, user.sub)
    return role_values


async def _user_has_permission(
    user: TokenPayload,
    permission: Permission,
    db: AsyncSession,
) -> bool:
    role_values = await _effective_role_values(user, db)
    return _roles_grant_permission(role_values, permission)


def has_permission(user: User, permission: Permission) -> bool:
    """Check whether a user has a specific permission.

    Args:
        user: The user object to check permissions for.
        permission: The permission to verify.

    Returns:
        True if the user has the permission, False otherwise.
    """
    # User.roles was part of the legacy ORM contract, while current role
    # assignments are persisted in the user_roles association table. Keep this
    # helper compatible with explicitly attached role assignments, and fail
    # closed when a plain User has no such compatibility data.
    role_values = _compatibility_role_values(user)
    return role_values is not None and _roles_grant_permission(role_values, permission)


def require_permission(permission: Permission) -> typing.Any:
    """Create a dependency that enforces a permission.

    Args:
        permission: The required permission.

    Returns:
        A dependency function that checks for the permission.
    """

    async def permission_checker(
        user: TokenPayload = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> TokenPayload:
        if not await _user_has_permission(user, permission, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        return user

    return permission_checker


# Common permission dependencies
RequireCreateStrategy = Depends(require_permission(Permission.CREATE_STRATEGY))
RequireUpdateStrategy = Depends(require_permission(Permission.UPDATE_STRATEGY))
RequireDeleteStrategy = Depends(require_permission(Permission.DELETE_STRATEGY))
RequireRunBacktest = Depends(require_permission(Permission.RUN_BACKTEST))
RequireExportBacktest = Depends(require_permission(Permission.EXPORT_BACKTEST))
RequireManageUsers = Depends(require_permission(Permission.MANAGE_USERS))


# Batch permission check
def require_any_permission(*permissions: Permission) -> typing.Any:
    """Require any one of the given permissions.

    Args:
        *permissions: Variable number of permissions to check against.

    Returns:
        A dependency function that checks for any of the specified permissions.
    """

    async def permission_checker(
        user: TokenPayload = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> TokenPayload:
        role_values = await _effective_role_values(user, db)
        has_any = any(
            _roles_grant_permission(role_values, permission) for permission in permissions
        )
        if not has_any:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions, requires one of: {', '.join([p.value for p in permissions])}",
            )
        return user

    return permission_checker
