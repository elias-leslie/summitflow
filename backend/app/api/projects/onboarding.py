"""SummitFlow project onboarding helpers."""

from __future__ import annotations

from ...logging_config import get_logger
from ...services.project_index import write_index_file
from ...storage.projects import get_project_root_path
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
    """Write the project's `.index.yaml`. Its files are backed up with the rest of the host."""
    root_path = get_project_root_path(project_id)
    if not root_path:
        raise ValueError(f"Project '{project_id}' has no root_path configured for onboarding")

    index_path = write_index_file(project_id)
    logger.info(
        "project_onboarding_complete",
        project_id=project_id,
        triggered_by=triggered_by,
        index_path=index_path,
    )
