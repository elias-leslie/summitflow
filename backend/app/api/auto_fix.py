"""Auto-Fix API - Endpoints for automated quality issue fixes."""

from typing import Any

from fastapi import APIRouter
from psycopg import Connection

from ..storage.connection import get_connection
from .dependencies import validate_project_exists
from .quality_gate_models import AutoFixRequest, AutoFixResponse

router = APIRouter()


def _run_fix_by_type(conn: Connection[Any], project_id: str, request: AutoFixRequest) -> dict[str, int]:
    """Dispatch fix logic based on check_type.

    Returns a results dict with fixed/failed/escalated counts.
    """
    from ..services.quality_gate import fix_unfixed_errors
    from ..services.quality_gate.fix_tests import fix_failing_tests

    results = {"fixed": 0, "failed": 0, "escalated": 0}

    if request.check_type == "pytest":
        test_results = fix_failing_tests(conn, project_id, limit=request.limit)
        results["fixed"] = test_results["fixed"]
        results["failed"] = test_results["failed"]
        results["escalated"] = test_results["escalated"]
    elif request.check_type in ("ruff", "types", "biome", "tsc"):
        lint_results = fix_unfixed_errors(
            conn, project_id, check_type=request.check_type, limit=request.limit
        )
        results["fixed"] = lint_results["fixed"]
        results["failed"] = lint_results["failed"]
        results["escalated"] = lint_results["escalated"]
    else:
        lint_results = fix_unfixed_errors(conn, project_id, limit=request.limit)
        results["fixed"] += lint_results["fixed"]
        results["failed"] += lint_results["failed"]
        results["escalated"] += lint_results["escalated"]

        test_results = fix_failing_tests(conn, project_id, limit=request.limit)
        results["fixed"] += test_results["fixed"]
        results["failed"] += test_results["failed"]
        results["escalated"] += test_results["escalated"]

    return results


def _build_fix_message(results: dict[str, int]) -> str:
    """Build a human-readable summary message from fix results."""
    total_attempts = results["fixed"] + results["failed"] + results["escalated"]
    if total_attempts == 0:
        return "No unfixed issues to process"
    if results["escalated"] > 0:
        return f"Fixed {results['fixed']}, {results['escalated']} escalated for investigation"
    if results["failed"] > 0:
        return f"Fixed {results['fixed']}, {results['failed']} still failing"
    return f"All {results['fixed']} issues fixed"


@router.post("/projects/{project_id}/quality/auto-fix")
async def trigger_auto_fix(
    project_id: str,
    request: AutoFixRequest,
) -> AutoFixResponse:
    """Trigger auto-fix for unfixed quality issues.

    Routes lint/type fixes through worker/supervisor agents and test failures
    through the reviewer/debugger path.

    Args:
        project_id: Project ID
        request: Auto-fix configuration

    Returns:
        AutoFixResponse with fix counts
    """
    validate_project_exists(project_id)

    with get_connection() as conn:
        results = _run_fix_by_type(conn, project_id, request)
        conn.commit()

    message = _build_fix_message(results)
    total_attempts = results["fixed"] + results["failed"] + results["escalated"]

    return AutoFixResponse(
        triggered=total_attempts > 0,
        check_type=request.check_type,
        **results,
        message=message,
    )
