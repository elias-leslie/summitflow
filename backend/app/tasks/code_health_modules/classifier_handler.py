"""Classification and task creation logic for code health findings."""

from __future__ import annotations

from ...logging_config import get_logger
from ...services.code_health.classifier import (
    ClassificationResult,
    ClassificationVerdict,
    CodeHealthClassifier,
    Finding,
)
from ...storage import code_health_lists

logger = get_logger(__name__)


def classify_and_process_findings(
    project_id: str,
    findings: list[Finding],
) -> tuple[dict[str, int], int]:
    """Classify findings and process them based on verdict.

    Args:
        project_id: Project ID
        findings: List of findings to classify

    Returns:
        Tuple of (classification_counts, memory_reused_count)
    """
    classified: dict[str, int] = {
        "false_positive": 0,
        "true_positive": 0,
        "needs_refactor": 0,
    }
    memory_reused = 0

    if not findings:
        return classified, memory_reused

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
            logger.info(f"Added to allow list: {finding.category} in {finding.file_path}")

        elif result.verdict == ClassificationVerdict.TRUE_POSITIVE:
            # Create a task for this finding
            create_health_task(project_id, finding, result)
            logger.info(f"Created task for: {finding.category} in {finding.file_path}")

        # NEEDS_REFACTOR goes to backlog (no immediate action)

    return classified, memory_reused


def create_health_task(
    project_id: str,
    finding: Finding,
    result: ClassificationResult,
) -> None:
    """Create a task for a TRUE_POSITIVE finding.

    Uses st CLI to create task in the SummitFlow system.
    """
    try:
        from ...storage.tasks import create_task

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
        )

    except Exception as e:
        logger.error(f"Failed to create task for finding: {e}")
