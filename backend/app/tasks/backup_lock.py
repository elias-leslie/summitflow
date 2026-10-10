"""Redis-based locking for backup operations."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event, Thread
from typing import cast
from uuid import uuid4

from ..logging_config import get_logger
from ..services.redis_pool import get_redis

BACKUP_LOCK_PREFIX = "summitflow:backup_lock:"
# Phase and cancel records belong to one lease owner token; outside the lock
# prefix so lease scans never count them as active work.
BACKUP_PHASE_PREFIX = "summitflow:backup_phase:"
BACKUP_CANCEL_PREFIX = "summitflow:backup_cancel:"
BACKUP_PHASE_TTL = 7 * 24 * 3600
BACKUP_LOCK_TTL = 900  # 15 minutes (matches time_limit)
BACKUP_LOCK_RENEW_INTERVAL = BACKUP_LOCK_TTL // 3
BACKUP_LOCK_JOIN_TIMEOUT = 6
_RESTART_GUARD_SOURCE = "__managed_worker_restart__"

_ACQUIRE_UNLESS_RESTARTING = """
if redis.call('exists', KEYS[2]) == 1 then
    return 0
end
return redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2])
"""

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


def has_active_backup_lease(source_id: str) -> bool:
    """Check worker ownership, not byte progress; errors must not imply orphaned."""
    return bool(get_redis().exists(_lock_key(source_id)))


def owns_backup_lease(source_id: str, owner_token: str) -> bool:
    """Do not let a delayed queued attempt adopt a newer attempt's lease."""
    value = get_redis().get(_lock_key(source_id))
    return value in {owner_token, owner_token.encode()}


def acquire_backup_lock(source_id: str) -> str | None:
    """Acquire a per-source lock and return its unique owner token."""
    owner_token = uuid4().hex
    result = get_redis().eval(
        _ACQUIRE_UNLESS_RESTARTING, 2,
        _lock_key(source_id), _lock_key(_RESTART_GUARD_SOURCE), owner_token, BACKUP_LOCK_TTL,
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


def _owned_record(prefix: str, source_id: str) -> dict[str, object] | None:
    """Return a phase/cancel record only while its writer still owns the lease."""
    redis = get_redis()
    raw = redis.get(prefix + source_id)
    if raw is None:
        return None
    try:
        record = json.loads(cast("str | bytes", raw))
    except (TypeError, ValueError):
        return None
    owner = record.get("owner") if isinstance(record, dict) else None
    return record if isinstance(owner, str) and owns_backup_lease(source_id, owner) else None


def publish_backup_phase(source_id: str, owner_token: str, *, operation: str, read_only: bool, **detail: object) -> None:
    """Record the running native operation so restart and cancel can judge safety."""
    record = {"owner": owner_token, "operation": operation, "read_only": read_only, "since": datetime.now(UTC).isoformat(), **detail}
    get_redis().set(BACKUP_PHASE_PREFIX + source_id, json.dumps(record), ex=BACKUP_PHASE_TTL)


def backup_phase(source_id: str) -> dict[str, object] | None:
    return _owned_record(BACKUP_PHASE_PREFIX, source_id)


def request_backup_cancel(source_id: str, *, force: bool) -> dict[str, object] | None:
    """Ask the current lease owner to stop; returns the phase it was asked during."""
    phase = backup_phase(source_id)
    if phase is None:
        return None
    get_redis().set(BACKUP_CANCEL_PREFIX + source_id, json.dumps({"owner": phase["owner"], "force": force}), ex=BACKUP_PHASE_TTL)
    return phase


def backup_cancel_request(source_id: str) -> dict[str, object] | None:
    return _owned_record(BACKUP_CANCEL_PREFIX, source_id)


def clear_backup_phase(source_id: str) -> None:
    get_redis().delete(BACKUP_PHASE_PREFIX + source_id, BACKUP_CANCEL_PREFIX + source_id)


def worker_restart_reserved() -> bool:
    return bool(get_redis().exists(_lock_key(_RESTART_GUARD_SOURCE)))


def _restart_blocker(source_id: str) -> str | None:
    """None when a restart may stop this lease's work with the repository unchanged."""
    phase = backup_phase(source_id)
    if phase is None:
        return source_id
    if phase.get("read_only"):
        return None
    cancel = phase.get("cancel_command")
    return f"{phase.get('label') or source_id} ({phase.get('operation')}, mutating since {phase.get('since')}; wait, or {cancel} --force)" if cancel else f"{source_id} ({phase.get('operation')})"


@contextmanager
def backup_worker_restart_guard() -> Iterator[Callable[[], None]]:
    """Refuse busy workers and atomically exclude new native backup admission.

    The existing owner-token lease/renewal conventions protect this short
    maintenance window; it is not a wait deadline or a backup cancellation.
    """
    token = uuid4().hex
    key = _lock_key(_RESTART_GUARD_SOURCE)
    try:
        acquired = get_redis().set(key, token, nx=True, ex=BACKUP_LOCK_TTL)
    except Exception as exc:
        raise BackupLockLeaseError("Cannot verify backup ownership; rebuild refused. Restore Redis access, then retry.") from exc
    if not acquired:
        raise BackupLockLeaseError("A backup worker restart is already reserved; retry after that rebuild finishes.")

    def assert_owned() -> None:
        try:
            # Upgraded workers cannot enter while the barrier is held. Recheck
            # for pre-upgrade workers during the first activation as well.
            # A read-only maintenance phase (check, dry-run) is stopped by the
            # restart with its repository unchanged; mutation cannot start
            # while this reservation exists.
            active = sorted(
                blocker
                for item in get_redis().scan_iter(match=f"{BACKUP_LOCK_PREFIX}*")
                if (decoded := item.decode() if isinstance(item, bytes) else str(item)) != key
                and (blocker := _restart_blocker(decoded.removeprefix(BACKUP_LOCK_PREFIX))) is not None
            )
            owned = owns_backup_lease(_RESTART_GUARD_SOURCE, token)
        except Exception as exc:
            raise BackupLockLeaseError("Cannot verify backup restart ownership; rebuild refused.") from exc
        if active:
            raise BackupLockLeaseError(
                "Backups active: " + ", ".join(active)
                + ". Wait for completion or explicitly cancel in Backups, then retry the rebuild."
            )
        if not owned:
            raise BackupLockLeaseError("Backup restart ownership lost; rebuild refused. Inspect active backups before retrying.")

    with maintain_backup_lock(_RESTART_GUARD_SOURCE, token):
        # Reserve before scanning: acquisition and the barrier check are one
        # Redis operation, so no upgraded source can slip through the scan.
        assert_owned()
        yield assert_owned


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
