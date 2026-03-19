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

# SQL queries
SQL_UPDATE_TASK_LINK = """
    UPDATE qa_issues
    SET st_task_id = %s, updated_at = NOW()
    WHERE id = %s
"""
