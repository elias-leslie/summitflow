"""Utility (on-demand) workflows for SummitFlow.

Post-scan explorer follow-ups and resolved-check workflows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from hatchet_sdk import Context

from ..hatchet_app import hatchet
from .models import ProjectInput


@hatchet.task(
    name="summitflow-check-resolved",
    input_validator=ProjectInput,
    execution_timeout="600s",
    retries=3,
    backoff_factor=2.0,
)
async def check_resolved_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import check_resolved_issues

    return await asyncio.to_thread(check_resolved_issues, input.project_id)


@hatchet.task(
    name="summitflow-page-health",
    input_validator=ProjectInput,
    execution_timeout="1200s",
    retries=3,
    backoff_factor=2.0,
)
async def page_health_wf(input: ProjectInput, ctx: Context) -> dict[str, Any]:
    from ..tasks.explorer_tasks import run_page_health_checks

    return await asyncio.to_thread(run_page_health_checks, input.project_id)


_POST_SCAN_WORKFLOWS = {"check_resolved": check_resolved_wf}


def make_post_scan_dispatch() -> Callable[[str, str, str], None]:
    """Return the sync (stage, task_id, project_id) callback used after explorer scans."""

    def dispatch(stage: str, task_id: str, project_id: str) -> None:
        workflow = _POST_SCAN_WORKFLOWS.get(stage)
        if workflow is None:
            raise ValueError(f"Unknown post-scan stage: {stage}")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(workflow.aio_run_no_wait(ProjectInput(project_id=project_id)))
        finally:
            loop.close()

    return dispatch
