"""Persisted owner checks for AFI's SDK-backed service APIs.

The authenticated JWT subject is the existing personal owner key.  Resource
ownership stays in the existing tables (for example ``Workspace.user_id`` and
portfolio owner fields); deployment configuration grants only the service
selectors bound to that exact subject.  No client header can select an owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import TokenPayload


@dataclass(frozen=True, slots=True)
class PersistedOwnerScope:
    """One active, persisted personal owner identity for an authenticated request."""

    owner_subject: str
    principal_kind: str


def _owner_scope_denied(code: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": "The authenticated owner scope is unavailable."},
    )


async def require_persisted_owner_scope(
    current_user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersistedOwnerScope:
    """Bind the JWT subject to an active persisted user before service access.

    ``UNKNOWN`` is retained for pre-classification users created by the
    existing principal-kind migration.  Such a user receives only the same
    exact owner selectors and stored RBAC permissions as before; this helper
    does not treat that value as proof of a human approver.  Explicit service
    principals and missing, inactive, or malformed owners fail closed.
    """

    if type(current_user) is not TokenPayload or type(current_user.sub) is not str:
        raise _owner_scope_denied("PERSISTED_OWNER_SCOPE_UNAVAILABLE")
    owner_subject = current_user.sub
    if not owner_subject or owner_subject != owner_subject.strip():
        raise _owner_scope_denied("PERSISTED_OWNER_SCOPE_UNAVAILABLE")

    owner = await db.get(User, owner_subject)
    if (
        owner is None
        or owner.is_active is not True
        or owner.principal_kind not in {"HUMAN", "UNKNOWN"}
    ):
        raise _owner_scope_denied("PERSISTED_OWNER_SCOPE_UNAVAILABLE")
    return PersistedOwnerScope(owner_subject=owner.id, principal_kind=owner.principal_kind)


async def require_persisted_human_principal(
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> PersistedOwnerScope:
    """Require authoritative HUMAN classification for maker/checker actions."""

    if owner.principal_kind != "HUMAN":
        raise _owner_scope_denied("PERSISTED_HUMAN_PRINCIPAL_REQUIRED")
    return owner
