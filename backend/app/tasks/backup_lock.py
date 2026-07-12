"""Redis-based locking for backup operations."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event, Thread
from uuid import uuid4

from ..logging_config import get_logger
from ..services.redis_pool import get_redis

BACKUP_LOCK_PREFIX = "summitflow:backup_lock:"
BACKUP_LOCK_TTL = 900  # 15 minutes (matches time_limit)
BACKUP_LOCK_RENEW_INTERVAL = BACKUP_LOCK_TTL // 3
BACKUP_LOCK_JOIN_TIMEOUT = 6

_RENEW_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_DELETE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

logger = get_logger(__name__)


class BackupLockLeaseError(RuntimeError):
    """Raised when an acquired backup lock can no longer be kept safely."""


def _lock_key(source_id: str) -> str:
    return f"{BACKUP_LOCK_PREFIX}{source_id}"


def acquire_backup_lock(source_id: str) -> str | None:
    """Acquire a per-source lock and return its unique owner token."""
    owner_token = uuid4().hex
    result = get_redis().set(
        _lock_key(source_id), owner_token, nx=True, ex=BACKUP_LOCK_TTL
    )
    return owner_token if result else None


def renew_backup_lock(source_id: str, owner_token: str) -> bool:
    """Renew a lock only while ``owner_token`` still owns it."""
    result = get_redis().eval(
        _RENEW_IF_OWNER,
        1,
        _lock_key(source_id),
        owner_token,
        BACKUP_LOCK_TTL,
    )
    return bool(result)


def release_backup_lock(source_id: str, owner_token: str) -> bool:
    """Release a lock only while ``owner_token`` still owns it."""
    result = get_redis().eval(
        _DELETE_IF_OWNER,
        1,
        _lock_key(source_id),
        owner_token,
    )
    return bool(result)


@contextmanager
def maintain_backup_lock(
    source_id: str,
    owner_token: str,
    *,
    renewal_interval_seconds: float | None = None,
) -> Iterator[None]:
    """Renew an acquired lock until the synchronous backup operation exits.

    Renewal and release both verify the owner token atomically. A lease failure
    is raised after the operation so callers cannot report unsafe success. If
    the operation itself raises, that original failure remains primary and the
    lease failure is attached as an exception note instead of masking it.
    """
    interval = (
        BACKUP_LOCK_RENEW_INTERVAL
        if renewal_interval_seconds is None
        else renewal_interval_seconds
    )
    if interval <= 0:
        raise ValueError("renewal_interval_seconds must be positive")

    stopped = Event()
    renewal_failures: list[BaseException] = []

    def _renew_until_stopped() -> None:
        while not stopped.wait(interval):
            try:
                renewed = renew_backup_lock(source_id, owner_token)
                if not renewed:
                    raise BackupLockLeaseError(
                        f"Backup lock ownership lost for {source_id}"
                    )
            except Exception as exc:
                renewal_failures.append(exc)
                stopped.set()
                return

    renewal_thread = Thread(
        target=_renew_until_stopped,
        name=f"backup-lock-{source_id}",
        daemon=True,
    )
    thread_started = False
    primary_error: BaseException | None = None
    try:
        renewal_thread.start()
        thread_started = True
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        stopped.set()
        if thread_started:
            renewal_thread.join(timeout=BACKUP_LOCK_JOIN_TIMEOUT)
            if renewal_thread.is_alive():
                renewal_failures.append(
                    BackupLockLeaseError(
                        f"Backup lock renewal did not stop for {source_id}"
                    )
                )

        release_failure: BaseException | None = None
        try:
            if not release_backup_lock(source_id, owner_token):
                release_failure = BackupLockLeaseError(
                    f"Backup lock ownership lost before release for {source_id}"
                )
        except Exception as exc:
            release_failure = exc

        failures = [*renewal_failures]
        if release_failure is not None:
            failures.append(release_failure)
        if failures:
            detail = "; ".join(str(failure) for failure in failures)
            logger.error(
                "backup_lock_lease_failed",
                source_id=source_id,
                error=detail,
            )
            if primary_error is not None:
                primary_error.add_note(f"Backup lock lease also failed: {detail}")
            else:
                first_failure = failures[0]
                if isinstance(first_failure, BackupLockLeaseError):
                    raise first_failure
                raise BackupLockLeaseError(
                    f"Backup lock lease failed for {source_id}: {detail}"
                ) from first_failure
