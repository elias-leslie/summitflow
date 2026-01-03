"""Explorer capability links storage - Link management between explorer entries and capabilities.

This module handles:
- Creating/deleting capability links
- Querying links by capability or entry
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection
from .explorer_entries import _row_to_entry, _to_iso_string


def create_capability_link(
    project_id: str,
    explorer_entry_id: int,
    capability_id: int,
    link_type: str,
) -> int:
    """Create a link between an explorer entry and a capability.

    Args:
        project_id: Project ID for scoping
        explorer_entry_id: ID of the explorer entry
        capability_id: ID of the capability
        link_type: Type of link (e.g., 'implements', 'exposes', 'required_by')

    Returns:
        ID of the created link
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO explorer_capability_links
                (project_id, explorer_entry_id, capability_id, link_type)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (project_id, explorer_entry_id, capability_id, link_type),
        )
        result = cur.fetchone()
        conn.commit()
        return result[0] if result else 0


def delete_capability_link(link_id: int) -> bool:
    """Delete a capability link by ID.

    Args:
        link_id: ID of the link to delete

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM explorer_capability_links
            WHERE id = %s
            RETURNING id
            """,
            (link_id,),
        )
        deleted = cur.fetchone() is not None
        conn.commit()
        return deleted


def get_capability_links(capability_id: int) -> list[dict[str, Any]]:
    """Get all explorer entries linked to a capability.

    Args:
        capability_id: ID of the capability

    Returns:
        List of linked explorer entries with link info
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ecl.id as link_id,
                ecl.link_type,
                ecl.created_at as link_created_at,
                ee.id, ee.project_id, ee.entry_type, ee.path, ee.name,
                ee.health_status, ee.metadata, ee.last_scanned_at,
                ee.created_at, ee.updated_at
            FROM explorer_capability_links ecl
            JOIN explorer_entries ee ON ecl.explorer_entry_id = ee.id
            WHERE ecl.capability_id = %s
            ORDER BY ecl.created_at DESC
            """,
            (capability_id,),
        )
        rows = cur.fetchall()

        return [
            {
                "link_id": row[0],
                "link_type": row[1],
                "link_created_at": _to_iso_string(row[2]),
                "entry": _row_to_entry(row[3:13]),
            }
            for row in rows
        ]


def get_entry_capabilities(explorer_entry_id: int) -> list[dict[str, Any]]:
    """Get all capabilities linked to an explorer entry.

    Args:
        explorer_entry_id: ID of the explorer entry

    Returns:
        List of linked capabilities with link info
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ecl.id as link_id,
                ecl.link_type,
                ecl.created_at as link_created_at,
                c.id, c.project_id, c.component_id, c.capability_id, c.name,
                c.description, c.status, c.priority,
                c.created_at, c.updated_at
            FROM explorer_capability_links ecl
            JOIN capabilities c ON ecl.capability_id = c.id
            WHERE ecl.explorer_entry_id = %s
            ORDER BY ecl.created_at DESC
            """,
            (explorer_entry_id,),
        )
        rows = cur.fetchall()

        return [
            {
                "link_id": row[0],
                "link_type": row[1],
                "link_created_at": _to_iso_string(row[2]),
                "capability": {
                    "id": row[3],
                    "project_id": row[4],
                    "component_id": row[5],
                    "capability_id": row[6],
                    "name": row[7],
                    "description": row[8],
                    "status": row[9],
                    "priority": row[10],
                    "created_at": _to_iso_string(row[11]),
                    "updated_at": _to_iso_string(row[12]),
                },
            }
            for row in rows
        ]
