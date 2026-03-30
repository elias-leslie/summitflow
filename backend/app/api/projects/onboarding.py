"""SummitFlow project onboarding helpers."""

from __future__ import annotations

import asyncio

from ...logging_config import get_logger
from ...services import explorer
from ...storage import backups as backup_store
from ...storage.projects import get_project_root_path
from ...tasks.backup_utils import calculate_next_run
from ...tasks.explorer_tasks import dispatch_post_scan_tasks
from ...workflows._models_backup import BackupInput
from ...workflows.pipeline import _make_dispatch_callback
from ...workflows.utility import backup_create_wf
from .models import ProjectOnboardingRequest, ProjectOnboardingResponse

logger = get_logger(__name__)

_INITIAL_BACKUP_NOTE = "Initial project onboarding backup"


def build_onboarding_response(
    project_id: str,
    request: ProjectOnboardingRequest,
) -> ProjectOnboardingResponse:
    """Build the queued onboarding response payload."""
    return ProjectOnboardingResponse(
        status="queued",
        project_id=project_id,
        backup_schedule_enabled=request.enable_backup_schedule,
        backup_frequency=request.backup_frequency,
        backup_retention_days=request.backup_retention_days,
        queue_initial_backup=request.queue_initial_backup,
    )


def _queue_initial_backup(project_id: str) -> None:
    """Queue a baseline backup for a newly onboarded project."""
    asyncio.run(
        backup_create_wf.aio_run_no_wait(
            BackupInput(
                project_id=project_id,
                source_id=project_id,
                note=_INITIAL_BACKUP_NOTE,
                backup_type="manual",
            )
        )
    )


def run_project_onboarding(
    project_id: str,
    request: ProjectOnboardingRequest,
    *,
    triggered_by: str,
) -> None:
    """Apply standard onboarding automation to an existing project."""
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise ValueError(f"Project '{project_id}' has no root_path configured for onboarding")

    source = backup_store.get_source(project_id)
    if not source:
        raise ValueError(f"Project '{project_id}' has no matching backup source to onboard")

    backup_store.update_source(
        project_id,
        enabled=request.enable_backup_schedule,
        frequency=request.backup_frequency,
        retention_days=request.backup_retention_days,
    )

    _, backup_total = backup_store.list_backups(project_id=project_id, limit=1)
    queued_initial_backup = False
    if request.queue_initial_backup and backup_total == 0:
        _queue_initial_backup(project_id)
        backup_store.update_source_last_run(
            project_id,
            calculate_next_run(request.backup_frequency),
        )
        queued_initial_backup = True
    elif source.get("last_run_at") is None and backup_store.get_latest_backup(project_id=project_id):
        backup_store.update_source_last_run(
            project_id,
            calculate_next_run(request.backup_frequency),
        )

    scan_result = explorer.run_scan_job(
        project_id,
        None,
        triggered_by=triggered_by,
    )
    dispatch_post_scan_tasks(_make_dispatch_callback(), project_id)
    logger.info(
        "project_onboarding_complete",
        project_id=project_id,
        backup_schedule_enabled=request.enable_backup_schedule,
        backup_frequency=request.backup_frequency,
        backup_retention_days=request.backup_retention_days,
        queued_initial_backup=queued_initial_backup,
        scan_id=scan_result.get("scan_id"),
    )
