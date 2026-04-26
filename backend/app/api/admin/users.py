"""Admin user management endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_admin
from app.db.database import get_db
from app.models.user import User
from pydantic import Field

from app.schemas.base import CamelModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin"])


# --- Schemas ---

class UserListResponse(CamelModel):
    id: int
    email: str
    display_name: str | None = None
    role: str
    locale: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserUpdateRequest(CamelModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    display_name: str | None = Field(None, max_length=100)


# --- Endpoints ---

@router.get("", response_model=list[UserListResponse])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all users ordered by creation date (newest first)."""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.patch("/{user_id}", response_model=UserListResponse)
async def update_user(
    user_id: int,
    body: UserUpdateRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role, active status, or display name."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent self-modification of role or active status
    if user.id == admin.id:
        if body.role is not None and body.role != admin.role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change your own role",
            )
        if body.is_active is not None and not body.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account",
            )

    changes: list[str] = []
    if body.role is not None:
        changes.append(f"role={body.role}")
        user.role = body.role
    if body.is_active is not None:
        changes.append(f"is_active={body.is_active}")
        user.is_active = body.is_active
    if body.display_name is not None:
        changes.append(f"display_name={body.display_name!r}")
        user.display_name = body.display_name

    await db.commit()
    await db.refresh(user)
    logger.info("Admin %s updated user %d: %s", admin.email, user.id, ", ".join(changes))
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user. Cannot delete yourself."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        await db.delete(user)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete user with associated data. Deactivate instead.",
        )
    logger.info("Admin %s deleted user %d (%s)", admin.email, user.id, user.email)
