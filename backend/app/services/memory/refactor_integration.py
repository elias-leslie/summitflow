"""Refactor Integration - Bridge between /refactor_it workflow and context memory.

Maps architecture violations to rule adherence observations for tracking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...storage import memory as memory_storage

logger = logging.getLogger(__name__)

# Mapping from violation types to rule files
VIOLATION_TO_RULE: dict[str, str] = {
    "layer_violation": "architecture-coherence.md",
    "boundary_violation": "architecture-coherence.md",
    "dry_violation": "code-cleanliness.md",
    "dead_code": "code-cleanliness.md",
    "duplicate_code": "code-cleanliness.md",
    "complexity_issue": "code-cleanliness.md",
    "security_issue": "security.md",
    "type_error": "type-safety.md",
    "import_cycle": "architecture-coherence.md",
}


def create_rule_adherence_from_violation(
    project_id: str,
    rule_file: str | None,
    violation_type: str,
    file_path: str,
    details: str,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Create a rule_adherence observation from a refactoring violation.

    This bridges the refactoring analysis to the rule adherence tracking system,
    allowing HealthChecker to report on rule compliance from refactoring findings.

    Args:
        project_id: The project ID
        rule_file: The rule file this violation relates to (e.g., "architecture-coherence.md")
                   If None, will be inferred from violation_type
        violation_type: Type of violation (e.g., "layer_violation", "dry_violation")
        file_path: The file where the violation was found
        details: Description of the violation
        session_id: Optional session ID, defaults to refactor timestamp

    Returns:
        Created observation dict, or None if creation failed
    """
    # Infer rule file if not provided
    if rule_file is None:
        rule_file = VIOLATION_TO_RULE.get(violation_type, "architecture-coherence.md")

    # Generate session ID if not provided
    if session_id is None:
        session_id = f"refactor-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    # Build the observation
    title = f"Rule violation: {violation_type} in {file_path}"
    narrative = f"""Found {violation_type} in {file_path}.

Rule file: {rule_file}
Details: {details}

This violation indicates the rule in {rule_file} was not followed.
"""

    facts = {
        "rule_file": rule_file,
        "followed": False,
        "violation_type": violation_type,
        "file_path": file_path,
        "source": "refactor_integration",
    }

    try:
        observation = memory_storage.create_observation(
            project_id=project_id,
            session_id=session_id,
            agent_type="refactor",
            observation_type="rule_adherence",
            title=title,
            narrative=narrative,
            confidence=0.9,  # High confidence - we found a concrete violation
            files_modified=[file_path],
            facts=facts,
            skip_memory_check=True,  # Refactor integration bypasses memory check
        )
        logger.info(f"Created rule_adherence observation for {violation_type} in {file_path}")
        return observation
    except Exception as e:
        logger.error(f"Failed to create rule_adherence observation: {e}")
        return None


def bulk_create_rule_adherence(
    project_id: str,
    violations: list[dict[str, Any]],
    session_id: str | None = None,
) -> dict[str, int]:
    """Bulk create rule_adherence observations from violations.

    Args:
        project_id: The project ID
        violations: List of violation dicts with keys:
            - violation_type: Type of violation
            - file_path: File where found
            - details: Description
            - rule_file: (optional) Rule file to associate
        session_id: Optional session ID, defaults to refactor timestamp

    Returns:
        Dict with created_count and failed_count
    """
    if session_id is None:
        session_id = f"refactor-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"

    created = 0
    failed = 0

    for v in violations:
        result = create_rule_adherence_from_violation(
            project_id=project_id,
            rule_file=v.get("rule_file"),
            violation_type=v.get("violation_type", "unknown"),
            file_path=v.get("file_path", "unknown"),
            details=v.get("details", "No details provided"),
            session_id=session_id,
        )
        if result:
            created += 1
        else:
            failed += 1

    return {"created_count": created, "failed_count": failed}
