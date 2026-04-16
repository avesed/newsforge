"""Authentication — JWT for users, API Key for machine consumers.

Refresh token design:
- Access token: short-lived (default 30min), no revocation infrastructure.
- Refresh token: long-lived (default 7d), carries a ``jti`` claim, revoked via
  Redis key ``jwt:refresh:revoked:<jti>`` (SET NX EX — atomic claim). Rotation
  on every ``/auth/refresh`` is implemented by *claiming* the incoming jti
  before minting new tokens: if the claim fails, we know the token has already
  been used (or logged out), so we reject — this both rotates and detects
  reuse in one atomic operation.
- Redis outage => fail-closed: refresh endpoint raises 503 rather than
  silently skipping revocation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import redis.exceptions
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.secrets import get_jwt_secret
from app.db.database import get_db
from app.db.redis import get_redis
from app.models.user import User

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"
REFRESH_DENYLIST_PREFIX = "jwt:refresh:revoked:"


def hash_password(password: str) -> str:
    # bcrypt has a 72-byte limit
    return pwd_context.hash(password[:72])


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain[:72], hashed)


def create_access_token(user_id: int, role: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {"sub": str(user_id), "role": role, "exp": expire, "type": "access"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=ALGORITHM)


def decode_refresh_token(token: str) -> tuple[int, str, int]:
    """Signature + structural validation of a refresh token.

    Returns ``(user_id, jti, exp_unix)``. Does NOT consult Redis — callers
    must then ``claim_refresh_jti`` to atomically detect reuse and revoke.
    Raises 401 on any structural invalidity.
    """
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")

    user_id = int(payload.get("sub", 0))
    jti = payload.get("jti")
    exp_ts = int(payload.get("exp", 0))
    if not user_id or not jti or not exp_ts:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed refresh token")

    return user_id, jti, exp_ts


async def claim_refresh_jti(jti: str, exp_ts: int) -> bool:
    """Atomically revoke a refresh jti; returns True iff the caller was the
    first to revoke it.

    Implemented as ``SET key 1 NX EX ttl``. Any concurrent caller racing to
    claim the same jti will see ``False`` and can safely reject as reuse.

    TTL equals the remaining natural lifetime of the token, bounded by the
    configured refresh expiry (clamped to at least 1s to avoid NOEXPIRE).

    Raises 503 if Redis is unreachable — we never "silently allow" a refresh
    without being able to atomically claim the jti.
    """
    settings = get_settings()
    now = int(datetime.now(timezone.utc).timestamp())
    # Floor at 60s (not 1s) so clock skew or future jose-leeway additions
    # can't leave a sub-second denylist window where reused tokens succeed.
    ttl = max(60, min(exp_ts - now, settings.jwt_refresh_token_expire_days * 86400))
    try:
        redis_client = await get_redis()
        # redis-py: set(..., nx=True) returns True if set, None if key existed.
        result = await redis_client.set(
            f"{REFRESH_DENYLIST_PREFIX}{jti}", "1", nx=True, ex=ttl
        )
    except redis.exceptions.RedisError:
        logger.warning("Redis unavailable during refresh jti claim", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Token revocation store unavailable",
        )

    return bool(result)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency — extract and validate JWT, return User."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = jwt.decode(credentials.credentials, get_jwt_secret(), algorithms=[ALGORITHM])
        user_id = int(payload.get("sub", 0))
        token_type = payload.get("type", "")
        if not user_id or token_type != "access":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Optional auth — returns None if no token provided."""
    if credentials is None:
        return None
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
