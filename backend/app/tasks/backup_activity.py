"""Observable, owner-cancellable backup work; elapsed time is not stall proof."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar, copy_context
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any, BinaryIO, cast

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_lock import BACKUP_LOCK_RENEW_INTERVAL

logger = get_logger(__name__)
ATTENTION_AFTER_SECONDS = 600
CONTROL_POLL_SECONDS = 1
CONTROL_DB_POLL_SECONDS = 5
_current: ContextVar[BackupActivity | None] = ContextVar("backup_activity", default=None)


class BackupCancelled(RuntimeError):
    """The owner or workflow requested cancellation of this attempt."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class BackupActivity:
    """One managed attempt, with sparse state writes and cooperative cancellation.

    The monitor renews workflow liveness, not a claim of byte progress. Remote
    progress is recorded only after verified readback. Opaque waits stay visible.
    """

    def __init__(
        self, run_id: str, cancelled: Callable[[], bool], renew: Callable[[], None], *, queued_attempt: bool = False,
    ) -> None:
        self.run_id = run_id
        self._workflow_cancelled = cancelled
        self._renew = renew
        self.cancelled = Event()
        self._stop = Event()
        self.backup_id: str | None = None
        self.state: dict[str, Any] = {}
        self._phase_started = time.monotonic()
        self._attention_after: float = ATTENTION_AFTER_SECONDS
        self._remote_inflight = False
        self.lease_owned: Callable[[], bool] | None = None
        self._bound = False
        self._queued_attempt = queued_attempt

    def __call__(self) -> None:
        """Verified-part callback checks cancellation; the monitor owns renewal."""
        self.check_cancelled()

    def _save(self, **updates: Any) -> None:
        self.state.update(updates)
        if self.backup_id:
            updated = backup_store.merge_backup_verification_json(
                self.backup_id, {"activity": updates},
                expected_activity_run_id=self.run_id if self._bound or self._queued_attempt else None,
            )
            if self._queued_attempt and not self._bound and updated is None:
                raise BackupCancelled("This queued backup attempt is no longer current")
            saved_activity = ((updated or {}).get("verification_json") or {}).get("activity") or {}
            if saved_activity.get("cancel_requested") is True:
                self.state["cancel_requested"] = True
                self.cancelled.set()

    def check_cancelled(self) -> None:
        if self.cancelled.is_set() or self._workflow_cancelled():
            self.cancelled.set()
            raise BackupCancelled("Backup cancellation requested; saved archives and verified Drive parts were retained")

    def start_phase(
        self, phase: str, object_name: str | None = None, attention_after: float = ATTENTION_AFTER_SECONDS,
    ) -> None:
        self.check_cancelled()
        self._phase_started = time.monotonic()
        self._attention_after = attention_after
        self._remote_inflight = phase in {"upload", "verification"}
        self._save(phase=phase, object_name=object_name, operation_started_at=_now(), attention=False)

    def verified_part(self, name: str) -> None:
        self.check_cancelled()
        self._save(
            last_verified_at=_now(), last_verified_part=name,
            verified_parts=int(self.state.get("verified_parts", 0)) + 1,
        )
        self._remote_inflight = False

    def record_local_archive(self, result: dict[str, Any]) -> None:
        """Make a verified local artifact retryable before remote work begins."""
        from .backup_utils import build_verification_kwargs

        if not self.backup_id or result.get("pending_path"):
            return
        verification = dict(result.get("verification") or {})
        if verification.get("verified") is not True:
            raise RuntimeError("Local recovery checkpoint requires verified archive")
        verification["activity"] = dict(self.state)
        verification["offsite"] = {"status": "pending"}
        backup_store.update_backup_status(
            self.backup_id, "completed", name=str(result.get("archive_name") or ""),
            location=str(result.get("location") or ""), size_bytes=int(result.get("total_bytes") or 0),
            **build_verification_kwargs(verification),
        )

    def record_offsite_result(self, result: dict[str, Any]) -> None:
        if result.get("status") == "failed":
            self.state["phase"] = "failed"

    def _monitor(self) -> None:
        last_poll = last_renew = time.monotonic()
        failures: set[str] = set()
        attention_saved_for: float | None = None
        while not self._stop.wait(CONTROL_POLL_SECONDS):
            now = time.monotonic()
            if self._workflow_cancelled():
                self.cancelled.set()
            # Advance before I/O: an unavailable DB must not turn this into a
            # one-second query/traceback loop or suppress workflow renewal.
            if self.backup_id and now - last_poll >= CONTROL_DB_POLL_SECONDS:
                last_poll = now
                if self.lease_owned is not None:
                    try:
                        if not self.lease_owned():
                            self.cancelled.set()
                        if "lease" in failures:
                            failures.remove("lease")
                            logger.info("backup_activity_lease_check_recovered", backup_id=self.backup_id)
                    except Exception:
                        if "lease" not in failures:
                            failures.add("lease")
                            logger.exception("backup_activity_lease_check_failed", backup_id=self.backup_id)
                        # Unknown ownership must not prevent the independent
                        # DB cancellation signal from reaching this process.
                try:
                    row = backup_store.get_backup(self.backup_id)
                    activity = ((row or {}).get("verification_json") or {}).get("activity") or {}
                    if activity.get("run_id") == self.run_id and activity.get("cancel_requested"):
                        self.cancelled.set()
                    if attention_saved_for != self._phase_started and now - self._phase_started >= self._attention_after:
                        self._save(attention=True)
                        attention_saved_for = self._phase_started
                    if "state" in failures:
                        failures.remove("state")
                        logger.info("backup_activity_monitor_recovered", backup_id=self.backup_id)
                except Exception:
                    if "state" not in failures:
                        failures.add("state")
                        logger.exception("backup_activity_monitor_failed", backup_id=self.backup_id)
            if now - last_renew >= BACKUP_LOCK_RENEW_INTERVAL:
                last_renew = now
                try:
                    self._renew()
                    if "renewal" in failures:
                        failures.remove("renewal")
                        logger.info("backup_activity_renewal_recovered", backup_id=self.backup_id)
                except Exception:
                    if "renewal" not in failures:
                        failures.add("renewal")
                        logger.exception("backup_activity_renewal_failed", backup_id=self.backup_id)

    @contextmanager
    def bind(self, backup_id: str) -> Iterator[None]:
        self.backup_id = backup_id
        self.cancelled.clear()
        self._stop.clear()
        self._remote_inflight = False
        self._attention_after = ATTENTION_AFTER_SECONDS
        self.state = {
            "backup_id": backup_id, "run_id": self.run_id, "active": True,
            "phase": "capture", "operation_started_at": _now(), "object_name": None,
            "last_verified_at": None, "last_verified_part": None, "verified_parts": 0,
            "attention": False, "cancel_requested": False, "remote_outcome_unknown": False,
        }
        previous = backup_store.get_backup(backup_id)
        previous_activity = ((previous or {}).get("verification_json") or {}).get("activity") or {}
        if previous_activity.get("run_id") == self.run_id and previous_activity.get("cancel_requested"):
            self.state["cancel_requested"] = True
            self.cancelled.set()
        self._phase_started = time.monotonic()
        self._bound = False
        self._save(**self.state)
        self._bound = True
        token = _current.set(self)
        monitor = Thread(target=self._monitor, name=f"backup-activity-{backup_id}", daemon=True)
        monitor.start()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            self._stop.set()
            monitor.join()
            is_cancelled = self.cancelled.is_set()
            try:
                self._save(
                    active=False, attention=False,
                    phase="cancelled" if is_cancelled else "failed" if failed or self.state.get("phase") == "failed" else "complete",
                    cancel_requested=is_cancelled,
                    remote_outcome_unknown=(is_cancelled or failed or self.state.get("phase") == "failed") and self._remote_inflight,
                )
            finally:
                _current.reset(token)


def current_activity() -> BackupActivity | None:
    return _current.get()


def check_backup_cancelled() -> None:
    activity = current_activity()
    if activity:
        activity.check_cancelled()


def backup_phase(phase: str, object_name: str | None = None) -> None:
    activity = current_activity()
    if activity:
        activity.start_phase(phase, object_name)


def record_local_archive(result: dict[str, Any]) -> None:
    activity = current_activity()
    if activity:
        activity.record_local_archive(result)


@contextmanager
def bind_backup_activity(backup_id: str, progress: Callable[[], None] | None) -> Iterator[None]:
    if isinstance(progress, BackupActivity):
        with progress.bind(backup_id):
            yield
    else:
        yield


def run_bulk_process(
    command: list[str], *, env: dict[str, str] | None = None, phase: str = "capture",
    object_name: str | None = None, attention_after: float = ATTENTION_AFTER_SECONDS,
    stdout_sink: Callable[[BinaryIO], None] | None = None, text: bool = True,
) -> subprocess.CompletedProcess[Any]:
    """Run owned bulk work without a wall-clock kill; cancellation kills/reaps it.

    stdout can stream into an existing compressor. stderr is drained by the OS
    into a private temporary file, avoiding pipe deadlocks and unbounded RAM.
    """
    activity = current_activity()
    if activity:
        activity.start_phase(phase, object_name, attention_after)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if stdout_sink else output,
            stderr=errors, env=env, start_new_session=True,
        )
        sink_errors: list[BaseException] = []
        sink_thread: Thread | None = None
        if stdout_sink:
            assert proc.stdout is not None

            def consume() -> None:
                try:
                    assert proc.stdout is not None
                    stdout_sink(cast(BinaryIO, proc.stdout))
                except BaseException as exc:
                    sink_errors.append(exc)

            context = copy_context()
            sink_thread = Thread(target=context.run, args=(consume,), name="backup-output", daemon=True)
            sink_thread.start()
        try:
            while True:
                if activity:
                    activity.check_cancelled()
                if sink_errors:
                    raise sink_errors[0]
                try:
                    proc.wait(timeout=CONTROL_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if sink_thread:
                while sink_thread.is_alive():
                    if activity:
                        activity.check_cancelled()
                    sink_thread.join(CONTROL_POLL_SECONDS)
            if sink_errors:
                raise sink_errors[0]
        except BaseException:
            # This process group was created by this exact attempt. Never
            # discover/kill by executable name or touch another backup's work.
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            if sink_thread:
                sink_thread.join()
            raise
        finally:
            if proc.stdout:
                proc.stdout.close()
        output.seek(0)
        # Match the existing transfer diagnostic tail; stdout remains complete
        # because Git metadata commands require its exact output.
        errors.seek(max(0, errors.tell() - 500))
        stdout, stderr = output.read(), errors.read()
        return subprocess.CompletedProcess(
            command, proc.returncode,
            stdout.decode(errors="replace") if text else stdout,
            stderr.decode(errors="replace") if text else stderr,
        )
