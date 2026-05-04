"""Project create/onboarding flow helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks, HTTPException

from ...storage import backups as backup_store
from .models import ProjectCreate, ProjectOnboardingRequest
from .public_urls import build_project_urls

TRIGGER_PROJECT_CREATE = "project_create"
TRIGGER_PROJECT_ONBOARD = "project_onboard"

ERR_ONBOARDING_REQUIRES_ROOT = "Project onboarding requires root_path"
ERR_ONBOARDING_REQUIRES_BACKUP = "Project onboarding requires a backup source"
ERR_BASE_URL_REQUIRED = (
    "Project base URL is required unless SummitFlow-hosted defaults are configured"
)


def resolve_project_create_urls(project: ProjectCreate) -> tuple[str, str | None]:
    if project.onboarding is not None and not project.root_path:
        raise HTTPException(status_code=400, detail=ERR_ONBOARDING_REQUIRES_ROOT)

    effective_base_url, effective_public_url = build_project_urls(
        project.id,
        base_url=project.base_url,
        public_url=project.public_url,
        root_path=project.root_path,
        summitflow_hosted=project.summitflow_hosted,
    )
    if not effective_base_url:
        raise HTTPException(status_code=400, detail=ERR_BASE_URL_REQUIRED)
    return effective_base_url, effective_public_url


def queue_project_create_work(
    project: ProjectCreate,
    background_tasks: BackgroundTasks,
    *,
    onboarding_runner: Callable[..., Any],
    scan_runner: Callable[..., Any],
) -> None:
    if project.onboarding is not None:
        background_tasks.add_task(
            onboarding_runner,
            project.id,
            project.onboarding,
            triggered_by=TRIGGER_PROJECT_CREATE,
        )
        return
    background_tasks.add_task(
        scan_runner,
        project.id,
        None,
        triggered_by=TRIGGER_PROJECT_CREATE,
    )


def validate_existing_project_onboarding(project_id: str, root_path: str | None) -> None:
    if not root_path:
        raise HTTPException(status_code=400, detail=ERR_ONBOARDING_REQUIRES_ROOT)
    if not backup_store.get_source(project_id):
        raise HTTPException(status_code=400, detail=ERR_ONBOARDING_REQUIRES_BACKUP)


def queue_existing_project_onboarding(
    project_id: str,
    request: ProjectOnboardingRequest,
    background_tasks: BackgroundTasks,
    *,
    onboarding_runner: Callable[..., Any],
) -> None:
    background_tasks.add_task(
        onboarding_runner,
        project_id,
        request,
        triggered_by=TRIGGER_PROJECT_ONBOARD,
    )
