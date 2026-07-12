"""Synchronous quality auto-fix job executed by the durable workflow worker."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from psycopg import Connection

from ..storage.connection import get_connection

FixableCheckType = Literal["pytest", "ruff", "types", "biome", "tsc"]


class AutoFixJobResult(TypedDict):
    """Serializable result returned by the quality auto-fix workflow."""

    triggered: bool
    check_type: FixableCheckType | None
    fixed: int
    failed: int
    escalated: int
    message: str


def _run_fix_by_type(
    conn: Connection[Any],
    project_id: str,
    check_type: FixableCheckType | None,
    limit: int,
) -> dict[str, int]:
    """Dispatch synchronous fix logic based on the requested check type."""
    from ..services.quality_gate import fix_unfixed_errors
    from ..services.quality_gate.fix_tests import fix_failing_tests

    results = {"fixed": 0, "failed": 0, "escalated": 0}

    if check_type == "pytest":
        test_results = fix_failing_tests(conn, project_id, limit=limit)
        results.update(test_results)
    elif check_type in ("ruff", "types", "biome", "tsc"):
        lint_results = fix_unfixed_errors(conn, project_id, check_type=check_type, limit=limit)
        results.update({key: int(lint_results[key]) for key in results})
    else:
        lint_results = fix_unfixed_errors(conn, project_id, limit=limit)
        for key in results:
            results[key] += int(lint_results[key])

        test_results = fix_failing_tests(conn, project_id, limit=limit)
        for key in results:
            results[key] += test_results[key]

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


def run_quality_auto_fix(
    project_id: str,
    check_type: FixableCheckType | None = None,
    limit: int = 10,
) -> AutoFixJobResult:
    """Run one auto-fix batch in a worker thread and commit its DB results."""
    with get_connection() as conn:
        results = _run_fix_by_type(conn, project_id, check_type, limit)
        conn.commit()

    total_attempts = results["fixed"] + results["failed"] + results["escalated"]
    return AutoFixJobResult(
        triggered=total_attempts > 0,
        check_type=check_type,
        fixed=results["fixed"],
        failed=results["failed"],
        escalated=results["escalated"],
        message=_build_fix_message(results),
    )
