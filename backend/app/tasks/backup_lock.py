"""Redis-based locking for backup operations."""

from __future__ import annotations

import redis

from ..config import REDIS_URL

BACKUP_LOCK_PREFIX = "summitflow:backup_lock:"
BACKUP_LOCK_TTL = 900  # 15 minutes (matches time_limit)


def _get_redis() -> redis.Redis:
    """Get Redis connection for backup locks."""
    return redis.from_url(f"{REDIS_URL}/1", decode_responses=False)


def acquire_backup_lock(source_id: str) -> bool:
    """Acquire a per-source backup lock. Returns True if acquired."""
    r = _get_redis()
    result = r.set(f"{BACKUP_LOCK_PREFIX}{source_id}", "1", nx=True, ex=BACKUP_LOCK_TTL)
    return bool(result)


def release_backup_lock(source_id: str) -> None:
    """Release a per-source backup lock."""
    r = _get_redis()
    r.delete(f"{BACKUP_LOCK_PREFIX}{source_id}")
