"""Redis-based locking for backup operations."""

from __future__ import annotations

from ..services.redis_pool import get_redis

BACKUP_LOCK_PREFIX = "summitflow:backup_lock:"
BACKUP_LOCK_TTL = 900  # 15 minutes (matches time_limit)


def acquire_backup_lock(source_id: str) -> bool:
    """Acquire a per-source backup lock. Returns True if acquired."""
    result = get_redis().set(f"{BACKUP_LOCK_PREFIX}{source_id}", "1", nx=True, ex=BACKUP_LOCK_TTL)
    return bool(result)


def release_backup_lock(source_id: str) -> None:
    """Release a per-source backup lock."""
    get_redis().delete(f"{BACKUP_LOCK_PREFIX}{source_id}")
