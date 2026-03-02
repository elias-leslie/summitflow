"""Constants and shared types for the task_issue_mapper service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QAIssue:
    """Minimal issue data needed for task mapping."""

    id: int
    project_id: str
    issue_type: str
    severity: str
    title: str
    description: str | None
    file_path: str | None
    st_task_id: str | None

# Command timeout (seconds)
ST_COMMAND_TIMEOUT = 30

# Task title max length
TASK_TITLE_MAX_LEN = 100

# Severity → priority mapping
SEVERITY_PRIORITY: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}
DEFAULT_PRIORITY = 2

# Issue type → domain mapping
BACKEND_ISSUE_TYPES: frozenset[str] = frozenset({"complexity", "dead_code", "missing_test"})
FRONTEND_ISSUE_TYPES: frozenset[str] = frozenset({"stale_page", "missing_component"})
DATABASE_ISSUE_TYPES: frozenset[str] = frozenset({"stale_table", "orphan_column"})
DEFAULT_DOMAIN = "backend"

# SQL queries
SQL_UPDATE_TASK_LINK = """
    UPDATE qa_issues
    SET st_task_id = %s, updated_at = NOW()
    WHERE id = %s
"""

SQL_SELECT_TASK_LINK = "SELECT st_task_id FROM qa_issues WHERE id = %s"

SQL_SELECT_ISSUE = """
    SELECT id, project_id, issue_type, severity, title,
           description, file_path, st_task_id
    FROM qa_issues
    WHERE id = %s
"""
