"""Adapt managed workflow liveness to the backup activity controller."""

import time
from datetime import timedelta

from hatchet_sdk import Context

from ..tasks.backup_activity import BackupActivity


def make_backup_progress_callback(ctx: Context, attempt_id: str | None = None) -> BackupActivity:
    """Let the controller's single monitor renew by elapsed whole seconds.

    Hatchet accepts whole seconds; retain fractional elapsed time for the next
    call. SDK refresh failures are logged by Context and the existing deadline
    remains the backstop. Renewal is liveness, never proof of remote progress;
    the activity controller separately exposes prolonged unknown waits.
    """
    extended_through = time.monotonic()

    def verified_progress() -> None:
        nonlocal extended_through
        elapsed = int(time.monotonic() - extended_through)
        if elapsed > 0:
            ctx.refresh_timeout(timedelta(seconds=elapsed))
            extended_through += elapsed

    return BackupActivity(attempt_id or str(ctx.workflow_run_id), ctx.done, verified_progress, queued_attempt=attempt_id is not None)
