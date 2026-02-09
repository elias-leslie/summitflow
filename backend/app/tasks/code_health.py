"""Background tasks for code health monitoring.

Tasks:
- daily_code_health_scan: Daily scan for code health issues
- weekly_deep_scan: Weekly deep analysis with trend comparison
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..services.explorer.base import get_project_config
from .code_health_modules import (
    classify_and_process_findings,
    collect_ast_metrics,
    scan_project_files,
)

logger = get_logger(__name__)


def daily_code_health_scan(
    project_id: str,
) -> dict[str, Any]:
    """Run daily code health scan for a project.

    Flow:
    1. Scan codebase for magic strings, compat cruft, health flags
    2. Filter findings against allow list
    3. Classify remaining findings with Gemini Flash
    4. Create tasks for TRUE_POSITIVE findings
    5. Add FALSE_POSITIVE findings to allow list

    Args:
        project_id: Project to scan

    Returns:
        Summary dict with scan results.
    """
    logger.info(f"daily_code_health_scan: starting for project={project_id}")

    # Get project config
    project = get_project_config(project_id)
    if not project:
        logger.error(f"daily_code_health_scan: project not found: {project_id}")
        return {"error": f"Project not found: {project_id}"}

    root_path = project.get("root_path")
    if not root_path:
        logger.error(f"daily_code_health_scan: no root_path for project: {project_id}")
        return {"error": f"No root_path configured for project: {project_id}"}

    backend_dir = project.get("backend_dir", "backend")

    # Scan files for findings
    findings, scanned_files, skipped_files = scan_project_files(
        project_id=project_id,
        root_path=root_path,
        backend_dir=backend_dir,
    )

    # Classify findings if any
    classified, memory_reused = classify_and_process_findings(
        project_id=project_id,
        findings=findings,
    )

    summary = {
        "task": "daily_code_health_scan",
        "project_id": project_id,
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "total_findings": len(findings),
        "classifications": classified,
        "memory_reused": memory_reused,
    }

    logger.info(f"daily_code_health_scan: completed {summary}")
    return summary


def weekly_deep_scan(
    project_id: str,
) -> dict[str, Any]:
    """Run weekly deep code health analysis.

    Flow:
    1. Run AST analysis on all Python files
    2. Compute health flags for each file
    3. Compare to previous week's metrics (trend analysis)
    4. Use Gemini Pro for degradation analysis if metrics worsen
    5. Create summary report

    Args:
        project_id: Project to analyze

    Returns:
        Summary dict with analysis results.
    """
    logger.info(f"weekly_deep_scan: starting for project={project_id}")

    # Get project config
    project = get_project_config(project_id)
    if not project:
        logger.error(f"weekly_deep_scan: project not found: {project_id}")
        return {"error": f"Project not found: {project_id}"}

    root_path = project.get("root_path")
    if not root_path:
        logger.error(f"weekly_deep_scan: no root_path for project: {project_id}")
        return {"error": f"No root_path configured for project: {project_id}"}

    backend_dir = project.get("backend_dir", "backend")

    # Collect AST metrics
    metrics, files_with_issues = collect_ast_metrics(
        root_path=root_path,
        backend_dir=backend_dir,
    )

    summary = {
        "task": "weekly_deep_scan",
        "project_id": project_id,
        "metrics": metrics,
        "files_with_issues": len(files_with_issues),
        "top_issues": files_with_issues[:10],  # Top 10 files with issues
    }

    logger.info(f"weekly_deep_scan: completed {summary}")
    return summary
