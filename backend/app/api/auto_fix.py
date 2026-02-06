"""Auto-Fix API - Endpoints for automated quality issue fixes."""

from fastapi import APIRouter

from ..storage.connection import get_connection
from .quality_gate_models import AutoFixRequest, AutoFixResponse
from .quality_gate_utils import validate_project_exists

router = APIRouter()


@router.post("/projects/{project_id}/quality/auto-fix")
async def trigger_auto_fix(
    project_id: str,
    request: AutoFixRequest,
) -> AutoFixResponse:
    """Trigger auto-fix for unfixed quality issues.

    Uses GEMINI_FLASH for lint/type errors (ruff, mypy, biome, tsc)
    and CLAUDE_SONNET for test failures (pytest).

    Args:
        project_id: Project ID
        request: Auto-fix configuration

    Returns:
        AutoFixResponse with fix counts
    """
    validate_project_exists(project_id)

    from ..services.quality_gate import fix_unfixed_errors
    from ..services.quality_gate.test_fix_agent import fix_failing_tests

    with get_connection() as conn:
        results = {"fixed": 0, "failed": 0, "escalated": 0}

        if request.check_type == "pytest":
            # Use test-specific fix agent
            test_results = fix_failing_tests(conn, project_id, limit=request.limit)
            results["fixed"] = test_results["fixed"]
            results["failed"] = test_results["failed"]
            results["escalated"] = test_results["escalated"]
        elif request.check_type in ("ruff", "mypy", "biome", "tsc"):
            # Use lint/type fix agent
            lint_results = fix_unfixed_errors(
                conn, project_id, check_type=request.check_type, limit=request.limit
            )
            results["fixed"] = lint_results["fixed"]
            results["failed"] = lint_results["failed"]
            results["escalated"] = lint_results["escalated"]
        else:
            # Fix all types
            lint_results = fix_unfixed_errors(conn, project_id, limit=request.limit)
            results["fixed"] += lint_results["fixed"]
            results["failed"] += lint_results["failed"]
            results["escalated"] += lint_results["escalated"]

            test_results = fix_failing_tests(conn, project_id, limit=request.limit)
            results["fixed"] += test_results["fixed"]
            results["failed"] += test_results["failed"]
            results["escalated"] += test_results["escalated"]

        conn.commit()

    total_attempts = results["fixed"] + results["failed"] + results["escalated"]
    if total_attempts == 0:
        message = "No unfixed issues to process"
    elif results["escalated"] > 0:
        message = f"Fixed {results['fixed']}, {results['escalated']} escalated for human review"
    elif results["failed"] > 0:
        message = f"Fixed {results['fixed']}, {results['failed']} still failing"
    else:
        message = f"All {results['fixed']} issues fixed"

    return AutoFixResponse(
        triggered=total_attempts > 0,
        check_type=request.check_type,
        **results,
        message=message,
    )
