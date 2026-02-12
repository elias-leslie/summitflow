"""Mockups core - Constants, ID generation, row mapping, and create operations."""

from __future__ import annotations

import uuid
from typing import Any

from ..connection import get_connection

# Mockup type constants
MOCKUP_TYPES = frozenset({"component", "page", "layout", "icon", "illustration"})

# Mockup status constants
MOCKUP_STATUSES = frozenset(
    {"generated", "pending_approval", "approved", "rejected", "applied", "archived"}
)

# Base SELECT columns for mockup queries
MOCKUP_SELECT_COLUMNS = """id, project_id, mockup_id, name, description, mockup_type,
       file_path, content, status, approved_at, approved_by, applied_at,
       task_id, page_path, version, parent_mockup_id, generator,
       generation_prompt, generation_time_ms, iteration_count, created_at, updated_at"""


def generate_mockup_id() -> str:
    """Generate a new mockup ID in the format mk-{uuid}."""
    return f"mk-{uuid.uuid4().hex[:12]}"


def _row_to_mockup(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to mockup dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "mockup_id": row[2],
        "name": row[3],
        "description": row[4],
        "mockup_type": row[5],
        "file_path": row[6],
        "content": row[7],
        "status": row[8],
        "approved_at": row[9].isoformat() if row[9] else None,
        "approved_by": row[10],
        "applied_at": row[11].isoformat() if row[11] else None,
        "task_id": row[12],
        "page_path": row[13],
        "version": row[14],
        "parent_mockup_id": row[15],
        "generator": row[16],
        "generation_prompt": row[17],
        "generation_time_ms": row[18],
        "iteration_count": row[19],
        "created_at": row[20].isoformat() if row[20] else None,
        "updated_at": row[21].isoformat() if row[21] else None,
    }


def get_mockup_by_db_id(db_id: int) -> dict[str, Any] | None:
    """Get a mockup by database ID (primary key)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {MOCKUP_SELECT_COLUMNS} FROM mockups WHERE id = %s",
            (db_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_mockup(row)


def create_mockup(
    project_id: str,
    name: str,
    *,
    description: str | None = None,
    mockup_type: str = "component",
    file_path: str | None = None,
    content: str | None = None,
    task_id: str | None = None,
    page_path: str | None = None,
    parent_mockup_id: int | None = None,
    generator: str | None = None,
    generation_prompt: str | None = None,
    generation_time_ms: int | None = None,
) -> dict[str, Any]:
    """Create a new mockup record.

    Args:
        project_id: Project ID
        name: Mockup name
        description: Mockup description (optional)
        mockup_type: Type of mockup (component, page, layout, icon, illustration)
        file_path: Path to mockup file (optional)
        content: Mockup content (optional, e.g., base64 image or HTML)
        task_id: Task ID if mockup is associated with a task
        page_path: Page path if mockup is for a specific page
        parent_mockup_id: Parent mockup ID for iterations
        generator: Name of the generator (e.g., "frontend-design", "gemini-2.0")
        generation_prompt: Prompt used to generate the mockup
        generation_time_ms: Time taken to generate the mockup

    Returns:
        Created mockup record
    """
    if mockup_type not in MOCKUP_TYPES:
        raise ValueError(f"Invalid mockup_type: {mockup_type}. Must be one of {MOCKUP_TYPES}")

    mockup_id = generate_mockup_id()

    # Determine version and iteration count from parent (single query)
    version = 1
    iteration_count = 1
    if parent_mockup_id:
        parent = get_mockup_by_db_id(parent_mockup_id)
        if parent:
            version = parent["version"] + 1
            iteration_count = parent["iteration_count"] + 1

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO mockups (
                project_id, mockup_id, name, description, mockup_type,
                file_path, content, status, task_id, page_path,
                version, parent_mockup_id, generator, generation_prompt,
                generation_time_ms, iteration_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'generated', %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {MOCKUP_SELECT_COLUMNS}
            """,
            (
                project_id,
                mockup_id,
                name,
                description,
                mockup_type,
                file_path,
                content,
                task_id,
                page_path,
                version,
                parent_mockup_id,
                generator,
                generation_prompt,
                generation_time_ms,
                iteration_count,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            raise RuntimeError("Failed to create mockup record")

        return _row_to_mockup(row)
