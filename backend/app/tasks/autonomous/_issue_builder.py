"""QA issue creation for autonomous tasks."""

from __future__ import annotations

from typing import Any

from app.storage import qa_issues as qa_storage


def create_refactor_issue(
    project_id: str,
    relative_path: str,
    complexity: float,
    lines: int,
    target_lines: int,
    reason: str,
) -> int:
    """Create a QA issue for refactoring.

    Args:
        project_id: Project ID
        relative_path: Relative file path
        complexity: Complexity score
        lines: Current line count
        target_lines: Target line count
        reason: Reason for refactoring

    Returns:
        Issue ID
    """
    file_name = relative_path.split("/")[-1]
    return qa_storage.upsert_issue(
        project_id=project_id,
        issue_type="complexity",
        file_path=relative_path,
        title=f"High complexity in {file_name}",
        severity="high" if complexity > 15 else "medium",
        description=f"Complexity: {complexity:.1f}, Lines: {lines}",
        metadata={
            "complexity_score": complexity,
            "lines_of_code": lines,
            "target_lines": target_lines,
            "reason": reason,
        },
    )


def create_schema_issue(
    project_id: str,
    table_name: str,
    violation_type: str,
    detail: str,
    severity: str,
    metadata: dict[str, Any],
) -> int:
    """Create a QA issue for schema violations.

    Args:
        project_id: Project ID
        table_name: Table name
        violation_type: Type of violation
        detail: Violation details
        severity: Severity level
        metadata: Additional metadata

    Returns:
        Issue ID
    """
    file_path = f"table:{table_name}"
    return qa_storage.upsert_issue(
        project_id=project_id,
        issue_type=violation_type,
        file_path=file_path,
        title=f"Schema: {detail}",
        severity="high" if severity == "error" else "medium",
        description=f"Table: {table_name}\nViolation: {detail}",
        metadata={
            "table_name": table_name,
            "violation_type": violation_type,
            **metadata,
        },
    )


def create_architecture_issue(
    project_id: str,
    violation_type: str,
    title: str,
    severity: str,
    violations_count: int,
    affected_files: list[str],
) -> int:
    """Create a QA issue for architecture violations.

    Args:
        project_id: Project ID
        violation_type: Type of violation
        title: Issue title
        severity: Severity level
        violations_count: Number of violations
        affected_files: List of affected files

    Returns:
        Issue ID
    """
    issue_path = f"architecture:{violation_type}"
    return qa_storage.upsert_issue(
        project_id=project_id,
        issue_type=violation_type,
        file_path=issue_path,
        title=f"Architecture: {title}",
        severity="high" if severity == "error" else "medium",
        description=f"Found {violations_count} {violation_type} violations across {len(affected_files)} files",
        metadata={
            "violation_type": violation_type,
            "affected_files": affected_files[:20],
            "violation_count": violations_count,
        },
    )
