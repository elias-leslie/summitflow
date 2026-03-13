"""Shared Redis connection pool for application services.

Provides a single connection pool for modules that need direct Redis access
(smoke tests, health monitor, backup locks, etc.) instead of each module
creating its own connection via redis.from_url().

The pub/sub module (pubsub.py) maintains its own pools for async/sync
separation — this module is for simple sync key-value operations.
"""

from __future__ import annotations

import redis

from ..config import REDIS_URL

# Module-level pool — lazy-initialized on first use
_pool: redis.ConnectionPool | None = None

# Redis DB 1 is the SummitFlow application database
_REDIS_DB = 1


def get_redis() -> redis.Redis:
    """Get a Redis client using the shared connection pool.

    Returns:
        redis.Redis instance backed by a shared ConnectionPool.
    """
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            f"{REDIS_URL}/{_REDIS_DB}",
            max_connections=10,
        )
    return redis.Redis(connection_pool=_pool)
