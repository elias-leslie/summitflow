"""Storage layer for explorer sub-elements (tabs, accordions, expandable rows)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

from ..logging_config import get_logger
from .connection import get_connection, get_cursor

logger = get_logger(__name__)


class ExplorerSubElement(TypedDict, total=False):
    """Sub-element within an explorer entry."""

    id: int
    explorer_entry_id: int
    selector: str
    element_type: str
    label: str | None
    discovered_at: datetime
    last_captured_at: datetime | None
    capture_count: int


def upsert_element(
    explorer_entry_id: int,
    selector: str,
    element_type: str,
    *,
    label: str | None = None,
) -> ExplorerSubElement:
    """Create or update a sub-element."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO explorer_sub_elements (
                explorer_entry_id, selector, element_type, label
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (explorer_entry_id, selector) DO UPDATE SET
                element_type = EXCLUDED.element_type,
                label = COALESCE(EXCLUDED.label, explorer_sub_elements.label)
            RETURNING id, explorer_entry_id, selector, element_type, label,
                      discovered_at, last_captured_at, capture_count
            """,
            (explorer_entry_id, selector, element_type, label),
        )
        row = cur.fetchone()
        conn.commit()

        if row is None:
            raise RuntimeError("Failed to upsert sub-element")

        return _row_to_element(row)


def get_elements_for_entry(explorer_entry_id: int) -> list[ExplorerSubElement]:
    """Get all sub-elements for an explorer entry."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, explorer_entry_id, selector, element_type, label,
                   discovered_at, last_captured_at, capture_count
            FROM explorer_sub_elements
            WHERE explorer_entry_id = %s
            ORDER BY element_type, label
            """,
            (explorer_entry_id,),
        )
        return [_row_to_element(row) for row in cur.fetchall()]


def mark_captured(element_id: int) -> ExplorerSubElement | None:
    """Update last_captured_at and increment capture_count."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE explorer_sub_elements
            SET last_captured_at = NOW(), capture_count = capture_count + 1
            WHERE id = %s
            RETURNING id, explorer_entry_id, selector, element_type, label,
                      discovered_at, last_captured_at, capture_count
            """,
            (element_id,),
        )
        row = cur.fetchone()
        conn.commit()

        return _row_to_element(row) if row else None


def bulk_upsert_elements(
    explorer_entry_id: int,
    elements: list[dict[str, str]],
) -> int:
    """Bulk upsert multiple sub-elements.

    Args:
        explorer_entry_id: The parent explorer entry ID
        elements: List of dicts with 'selector', 'element_type', and optional 'label'

    Returns:
        Number of elements upserted
    """
    if not elements:
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        # Use executemany for bulk insert
        cur.executemany(
            """
            INSERT INTO explorer_sub_elements (
                explorer_entry_id, selector, element_type, label
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (explorer_entry_id, selector) DO UPDATE SET
                element_type = EXCLUDED.element_type,
                label = COALESCE(EXCLUDED.label, explorer_sub_elements.label)
            """,
            [
                (
                    explorer_entry_id,
                    el.get("selector"),
                    el.get("element_type"),
                    el.get("label"),
                )
                for el in elements
            ],
        )
        conn.commit()

        return len(elements)


def _row_to_element(row: tuple[Any, ...]) -> ExplorerSubElement:
    """Convert database row to ExplorerSubElement."""
    return {
        "id": row[0],
        "explorer_entry_id": row[1],
        "selector": row[2],
        "element_type": row[3],
        "label": row[4],
        "discovered_at": row[5],
        "last_captured_at": row[6],
        "capture_count": row[7],
    }
