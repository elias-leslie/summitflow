"""Coverage analysis - Calculate test coverage statistics.

Analyzes endpoints and pages to determine coverage by TDD capabilities.
"""

from __future__ import annotations

from typing import Any, TypedDict

from ...storage import explorer as explorer_storage


class CoverageStats(TypedDict):
    """Coverage statistics for an entry type."""

    total: int
    covered: int
    uncovered: int
    coverage_pct: float


class CoverageSummary(TypedDict):
    """Complete coverage summary for endpoints and pages."""

    endpoints: CoverageStats
    pages: CoverageStats


def get_coverage_summary(project_id: str) -> CoverageSummary:
    """Calculate coverage stats for endpoints and pages.

    Args:
        project_id: Project ID for scoping

    Returns:
        Coverage statistics for endpoints and pages
    """
    gaps = explorer_storage.get_coverage_gaps(project_id)
    endpoints = explorer_storage.get_entries(project_id, {"type": "endpoint", "limit": 10000})
    pages = explorer_storage.get_entries(project_id, {"type": "page", "limit": 10000})

    return {
        "endpoints": _calculate_stats(
            total=len(endpoints),
            uncovered=gaps["summary"]["endpoint_count"]
        ),
        "pages": _calculate_stats(
            total=len(pages),
            uncovered=gaps["summary"]["page_count"]
        ),
    }


def _calculate_stats(total: int, uncovered: int) -> CoverageStats:
    """Calculate coverage statistics for a single entry type."""
    covered = total - uncovered
    coverage_pct = round((covered / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "covered": covered,
        "uncovered": uncovered,
        "coverage_pct": coverage_pct,
    }


def generate_recommendation(
    components: list[dict[str, Any]],
    tests: list[dict[str, Any]],
    coverage: CoverageSummary,
) -> str:
    """Generate a natural language recommendation for TDD setup.

    Args:
        components: List of suggested components
        tests: List of discovered test files
        coverage: Coverage summary statistics

    Returns:
        Human-readable recommendation string
    """
    parts: list[str] = []

    if components:
        parts.append(f"Found {len(components)} potential components to organize.")

    if tests:
        parts.append(f"Discovered {len(tests)} existing test files.")

    endpoint_cov = coverage["endpoints"]["coverage_pct"]
    page_cov = coverage["pages"]["coverage_pct"]

    if endpoint_cov < 50:
        parts.append(
            f"Endpoint coverage is low ({endpoint_cov}%). Consider adding capability links."
        )
    if page_cov < 50:
        parts.append(f"Page coverage is low ({page_cov}%). Consider adding capability links.")

    if not parts:
        parts.append("Codebase looks well organized. Run a scan to update metrics.")

    return " ".join(parts)
