"""Redis cache service -- simple get/set with TTL.

Key patterns:
  cache:articles:{category}:{page}  TTL=60s
  cache:article:{id}                TTL=300s
  cache:homepage:{page}             TTL=30s
  cache:categories                  TTL=600s
  cache:admin:stats                 TTL=15s

IMPORTANT: Redis is configured with decode_responses=True,
so use orjson.dumps(...).decode() for SET, orjson.loads(value) for GET.
Do NOT use decorators (conflicts with FastAPI DI). Instead, check cache
at the top of endpoint functions with early return.
"""

from __future__ import annotations

import logging

import orjson

from app.db.redis import get_redis

logger = logging.getLogger(__name__)

CACHE_PREFIX = "cache:"


class CacheService:
    """Simple Redis cache with namespace prefix."""

    @staticmethod
    async def get(key: str) -> dict | list | None:
        """Get cached value. Returns None on miss or error."""
        try:
            redis = await get_redis()
            value = await redis.get(f"{CACHE_PREFIX}{key}")
            if value:
                return orjson.loads(value)
        except Exception:
            logger.debug("Cache miss/error for key: %s", key)
        return None

    @staticmethod
    async def set(key: str, data: dict | list, ttl_seconds: int = 60) -> None:
        """Set cached value with TTL."""
        try:
            redis = await get_redis()
            await redis.set(
                f"{CACHE_PREFIX}{key}",
                orjson.dumps(data).decode(),
                ex=ttl_seconds,
            )
        except Exception:
            logger.debug("Cache set error for key: %s", key)

    @staticmethod
    async def invalidate(key: str) -> None:
        """Delete a specific cache key."""
        try:
            redis = await get_redis()
            await redis.delete(f"{CACHE_PREFIX}{key}")
        except Exception:
            pass

    @staticmethod
    async def invalidate_pattern(pattern: str) -> None:
        """Delete all keys matching pattern (e.g., 'articles:*')."""
        try:
            redis = await get_redis()
            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor, match=f"{CACHE_PREFIX}{pattern}", count=100
                )
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            logger.debug("Cache invalidate pattern error: %s", pattern)


cache = CacheService()
