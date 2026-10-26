"""SummitFlow project onboarding helpers."""

from __future__ import annotations

from ...logging_config import get_logger
from ...services import explorer
from ...storage.projects import get_project_root_path
from ...tasks.explorer_tasks import dispatch_post_scan_tasks
from ...workflows.utility import make_post_scan_dispatch
from .models import ProjectOnboardingRequest, ProjectOnboardingResponse

logger = get_logger(__name__)


def build_onboarding_response(
    project_id: str,
    request: ProjectOnboardingRequest,
) -> ProjectOnboardingResponse:
    """Build the queued onboarding response payload."""
    return ProjectOnboardingResponse(status="queued", project_id=project_id)


def run_project_onboarding(
    project_id: str,
    request: ProjectOnboardingRequest,
    *,
    triggered_by: str,
) -> None:
    """Scan an existing project and sync its tasks. Its files are backed up with the rest of the host."""
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise ValueError(f"Project '{project_id}' has no root_path configured for onboarding")

    scan_result = explorer.run_scan_job(
        project_id,
        None,
        triggered_by=triggered_by,
    )
    dispatch_post_scan_tasks(make_post_scan_dispatch(), project_id)
    logger.info("project_onboarding_complete", project_id=project_id, scan_id=scan_result.get("scan_id"))
