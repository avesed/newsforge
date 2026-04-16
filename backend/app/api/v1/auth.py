"""Authentication endpoints — register, login, refresh, logout, me."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    claim_refresh_jti,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check if email exists
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Bootstrap: if no admin exists yet, promote this registrant to admin.
    # If FIRST_ADMIN_EMAIL is configured, it acts as a whitelist — only that
    # email may claim the bootstrap admin slot.
    settings = get_settings()
    role = "user"
    admin_exists = (
        await db.execute(select(User.id).where(User.role == "admin").limit(1))
    ).first()
    if not admin_exists:
        if not settings.first_admin_email or body.email == settings.first_admin_email:
            role = "admin"

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        role=role,
    )
    db.add(user)
    # Commit before minting tokens so we don't hand out a token referencing a
    # row that could still be rolled back by the outer dependency scope.
    await db.commit()
    await db.refresh(user)

    return _issue_tokens(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    user_id, jti, exp_ts = decode_refresh_token(body.refresh_token)

    # Atomically revoke the incoming jti BEFORE minting anything. Two concurrent
    # refreshes with the same token therefore cannot both succeed — the loser
    # gets `False` and we treat it as a reuse attempt.
    claimed = await claim_refresh_jti(jti, exp_ts)
    if not claimed:
        logger.warning("Refresh token reuse detected for user_id=%s jti=%s", user_id, jti)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token already used",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return _issue_tokens(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest | None = None):
    """Revoke the supplied refresh token on a best-effort basis.

    Missing body or invalid token are silently accepted — the user is logging
    out from the UI regardless. Redis outage is logged but does not fail the
    request; the token will still expire naturally at its ``exp``.
    """
    if body is None or not body.refresh_token:
        return None

    try:
        _user_id, jti, exp_ts = decode_refresh_token(body.refresh_token)
    except HTTPException:
        # Token already invalid/expired — nothing to do.
        return None

    try:
        await claim_refresh_jti(jti, exp_ts)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            logger.warning(
                "Logout could not revoke jti=%s: revocation store unavailable", jti
            )
            return None
        raise

    return None


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user
