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
_client: redis.Redis | None = None

# Redis DB 1 is the SummitFlow application database
_REDIS_DB = 1


def create_redis_client(
    url: str = REDIS_URL,
    *,
    default_db: int = _REDIS_DB,
    **connection_kwargs: object,
) -> redis.Redis:
    """Create a client while preserving an explicit URL database selection.

    redis-py gives URL path/query values precedence over keyword defaults, so
    ``db=default_db`` applies only when the configured URL does not select a
    database.  This also preserves passwords, query parameters, and ``rediss``.
    """
    return redis.Redis.from_url(url, db=default_db, **connection_kwargs)


def get_redis() -> redis.Redis:
    """Get a Redis client using the shared connection pool.

    Returns:
        redis.Redis instance backed by a shared ConnectionPool.
    """
    global _pool, _client
    if _client is None:
        _client = create_redis_client(
            REDIS_URL,
            max_connections=10,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
        _pool = _client.connection_pool
    return _client
