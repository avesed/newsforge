"""Health check endpoints."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "newsforge"}


@router.get("/health/ready")
async def readiness_check():
    """Check database and Redis connectivity."""
    checks = {}

    # Database
    try:
        from sqlalchemy import text

        from app.db.database import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        from app.db.redis import get_redis

        redis = await get_redis()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if all_ok else "degraded", "checks": checks}


@router.get("/health/llm")
async def llm_health():
    """Check if any LLM provider is configured (DB or env)."""
    from app.core.llm.gateway import get_llm_gateway

    gateway = get_llm_gateway()
    configured = await gateway.is_configured()
    return {"configured": configured, "status": "ok" if configured else "not_configured"}
