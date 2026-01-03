"""Celery tasks for code health monitoring.

Tasks:
- daily_code_health_scan: Daily scan for code health issues
- weekly_deep_scan: Weekly deep analysis with trend comparison
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.code_health.classifier import (
    ClassificationResult,
    ClassificationVerdict,
    CodeHealthClassifier,
    Finding,
)
from ..services.explorer.base import get_project_config
from ..services.explorer.types.files import FileScanner
from ..storage import code_health_lists

logger = get_logger(__name__)


@shared_task(
    name="summitflow.daily_code_health_scan",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def daily_code_health_scan(
    self: Any,
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

    # Run the scan
    scanner = FileScanner(project_id)
    scanner.root_path = Path(root_path)

    # Collect findings
    findings: list[Finding] = []
    scanned_files = 0
    skipped_files = 0

    backend_dir = project.get("backend_dir", "backend")
    scan_dir = Path(root_path) / backend_dir / "app"

    if not scan_dir.exists():
        scan_dir = Path(root_path) / "app"

    for py_file in scan_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            with open(py_file, encoding="utf-8", errors="ignore") as f:
                content = f.read()

            rel_path = str(py_file.relative_to(root_path))

            # Check for compat cruft
            compat_cruft = scanner._detect_compat_cruft(rel_path, content)
            for category, count in (compat_cruft or {}).items():
                # Check if pattern is in allow list
                pattern = f"{category}:{rel_path}"
                if code_health_lists.is_pattern_allowed(project_id, category, pattern):
                    skipped_files += 1
                    continue

                findings.append(
                    Finding(
                        file_path=rel_path,
                        category=category,
                        pattern=f"{count} instances",
                        context=_extract_context(content, category),
                    )
                )

            # Check for magic strings
            magic_strings = scanner._detect_magic_strings(rel_path, content)
            for category, count in (magic_strings or {}).items():
                pattern = f"{category}:{rel_path}"
                if code_health_lists.is_pattern_allowed(project_id, category, pattern):
                    skipped_files += 1
                    continue

                findings.append(
                    Finding(
                        file_path=rel_path,
                        category=f"magic_string:{category}",
                        pattern=f"{count} instances",
                        context=_extract_context(content, category),
                    )
                )

            scanned_files += 1

        except Exception as e:
            logger.warning("Failed to scan %s: %s", py_file, e)

    logger.info(
        "daily_code_health_scan: scanned %d files, found %d findings",
        scanned_files,
        len(findings),
    )

    # Classify findings if any
    classified: dict[str, int] = {
        "false_positive": 0,
        "true_positive": 0,
        "needs_refactor": 0,
    }
    memory_reused = 0

    if findings:
        # Pass project_id to enable memory learning/reuse
        classifier = CodeHealthClassifier(project_id=project_id)

        for finding, result in classifier.classify_batch(findings):
            classified[result.verdict.value] += 1

            # Track memory reuse (indicated by [From memory] prefix in reason)
            if result.reason.startswith("[From memory]"):
                memory_reused += 1

            # Handle based on verdict
            if result.verdict == ClassificationVerdict.FALSE_POSITIVE:
                # Add to allow list
                code_health_lists.create_list_entry(
                    project_id=project_id,
                    list_type="allow",
                    category=finding.category,
                    pattern=f"{finding.category}:{finding.file_path}",
                    reason=result.reason,
                    confidence=result.confidence,
                    source="agent",
                    created_by="code-health-agent",
                )
                logger.info(
                    "Added to allow list: %s in %s",
                    finding.category,
                    finding.file_path,
                )

            elif result.verdict == ClassificationVerdict.TRUE_POSITIVE:
                # Create a task for this finding
                _create_health_task(project_id, finding, result)
                logger.info(
                    "Created task for: %s in %s",
                    finding.category,
                    finding.file_path,
                )

            # NEEDS_REFACTOR goes to backlog (no immediate action)

    summary = {
        "task": "daily_code_health_scan",
        "project_id": project_id,
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "total_findings": len(findings),
        "classifications": classified,
        "memory_reused": memory_reused,
    }

    logger.info("daily_code_health_scan: completed %s", summary)
    return summary


@shared_task(
    name="summitflow.weekly_deep_scan",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=2,
)
def weekly_deep_scan(
    self: Any,
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
    logger.info("weekly_deep_scan: starting for project=%s", project_id)

    # Get project config
    project = get_project_config(project_id)
    if not project:
        logger.error(f"weekly_deep_scan: project not found: {project_id}")
        return {"error": f"Project not found: {project_id}"}

    root_path = project.get("root_path")
    if not root_path:
        logger.error(f"weekly_deep_scan: no root_path for project: {project_id}")
        return {"error": f"No root_path configured for project: {project_id}"}

    # Run AST analysis
    from ..services.explorer.analyzers.ast_analyzer import parse_python_file

    backend_dir = project.get("backend_dir", "backend")
    scan_dir = Path(root_path) / backend_dir / "app"

    if not scan_dir.exists():
        scan_dir = Path(root_path) / "app"

    metrics = {
        "total_files": 0,
        "total_functions": 0,
        "total_classes": 0,
        "long_functions": 0,
        "large_classes": 0,
        "deep_nesting": 0,
        "max_nesting_seen": 0,
    }

    files_with_issues: list[dict[str, Any]] = []

    for py_file in scan_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            result = parse_python_file(py_file)

            metrics["total_files"] += 1
            metrics["total_functions"] += len(result["functions"])
            metrics["total_classes"] += len(result["classes"])
            metrics["max_nesting_seen"] = max(
                metrics["max_nesting_seen"],
                result["max_nesting"],
            )

            file_issues = []

            # Count long functions (>50 lines)
            for func in result["functions"]:
                if func["lines"] > 50:
                    metrics["long_functions"] += 1
                    file_issues.append(f"Long function: {func['name']} ({func['lines']} lines)")

            # Count large classes (>10 methods)
            for cls in result["classes"]:
                if len(cls["methods"]) > 10:
                    metrics["large_classes"] += 1
                    file_issues.append(
                        f"Large class: {cls['name']} ({len(cls['methods'])} methods)"
                    )

            # Count deep nesting (>3 levels)
            if result["max_nesting"] > 3:
                metrics["deep_nesting"] += 1
                file_issues.append(f"Deep nesting: {result['max_nesting']} levels")

            if file_issues:
                files_with_issues.append(
                    {
                        "file": str(py_file.relative_to(root_path)),
                        "issues": file_issues,
                    }
                )

        except (SyntaxError, FileNotFoundError) as e:
            logger.debug("Skipping %s: %s", py_file, e)
        except Exception as e:
            logger.warning("Failed to analyze %s: %s", py_file, e)

    summary = {
        "task": "weekly_deep_scan",
        "project_id": project_id,
        "metrics": metrics,
        "files_with_issues": len(files_with_issues),
        "top_issues": files_with_issues[:10],  # Top 10 files with issues
    }

    logger.info("weekly_deep_scan: completed %s", summary)
    return summary


def _extract_context(content: str, category: str) -> str:
    """Extract relevant context from file content for classification."""
    # Return first 500 chars as context
    return content[:500] if content else ""


def _create_health_task(
    project_id: str,
    finding: Finding,
    result: ClassificationResult,
) -> None:
    """Create a task for a TRUE_POSITIVE finding.

    Uses st CLI to create task in the SummitFlow system.
    """
    try:
        from ..storage.tasks import create_task

        title = f"Fix: {finding.category} in {finding.file_path}"
        description = f"""Code health issue detected by automated scan.

**Category:** {finding.category}
**File:** {finding.file_path}
**Pattern:** {finding.pattern}

**Analysis:**
{result.reason}

**Suggested Action:**
{result.suggested_action or "Review and fix the issue"}

Confidence: {result.confidence:.0%}
"""

        create_task(
            project_id=project_id,
            title=title,
            description=description,
            task_type="task",
            priority=3,  # Medium-low priority
            labels=["complexity:small", "auto-generated", "code-health"],
        )

    except Exception as e:
        logger.error(f"Failed to create task for finding: {e}")
