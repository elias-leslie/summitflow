"""Access-control persistence for SummitFlow sharing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException

from .connection import get_connection, get_cursor

ACCESS_SECTIONS = {"design"}


@dataclass(frozen=True)
class AccessUser:
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AccessGrant:
    user_email: str
    project_id: str
    section: str
    created_at: datetime


def normalize_email(value: str) -> str:
    """Return a canonical email address for identity and grants."""
    return value.strip().lower()


def parse_owner_emails(value: str) -> set[str]:
    """Parse comma/space separated owner emails from configuration."""
    if not value:
        return set()
    raw = value.replace("\n", ",").replace(";", ",").split(",")
    return {normalize_email(item) for item in raw if normalize_email(item)}


def bootstrap_owners(owner_emails: set[str]) -> None:
    """Ensure configured owners exist as active owner users."""
    if not owner_emails:
        return
    with get_connection() as conn, conn.cursor() as cur:
        for email in owner_emails:
            cur.execute(
                """
                INSERT INTO share_users (email, role, is_active)
                VALUES (%s, 'owner', TRUE)
                ON CONFLICT (email) DO UPDATE
                SET role = 'owner', is_active = TRUE, updated_at = NOW()
                """,
                (email,),
            )
        conn.commit()


def get_user(email: str) -> AccessUser | None:
    """Return an access user by email."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT email, role, is_active, created_at, updated_at
            FROM share_users
            WHERE email = %s
            """,
            (normalize_email(email),),
        )
        row = cur.fetchone()
    if not row:
        return None
    return AccessUser(
        email=row[0],
        role=row[1],
        is_active=row[2],
        created_at=row[3],
        updated_at=row[4],
    )


def count_active_owners() -> int:
    """Return active owner count."""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM share_users WHERE role = 'owner' AND is_active = TRUE")
        row = cur.fetchone()
    return int(row[0] if row else 0)


def upsert_user(email: str, role: str = "viewer", *, is_active: bool = True) -> AccessUser:
    """Create or update a user."""
    email = normalize_email(email)
    if role not in {"owner", "viewer"}:
        raise HTTPException(status_code=400, detail="role must be owner or viewer")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")

    existing = get_user(email)
    if (
        existing
        and existing.role == "owner"
        and existing.is_active
        and (role != "owner" or not is_active)
        and count_active_owners() <= 1
    ):
        raise HTTPException(status_code=400, detail="Cannot remove the last active owner")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO share_users (email, role, is_active)
            VALUES (%s, %s, %s)
            ON CONFLICT (email) DO UPDATE
            SET role = EXCLUDED.role, is_active = EXCLUDED.is_active, updated_at = NOW()
            RETURNING email, role, is_active, created_at, updated_at
            """,
            (email, role, is_active),
        )
        row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=500, detail="Failed to persist access user")
    return AccessUser(
        email=row[0],
        role=row[1],
        is_active=row[2],
        created_at=row[3],
        updated_at=row[4],
    )


def delete_user(email: str) -> None:
    """Delete a user, protecting the final active owner."""
    email = normalize_email(email)
    user = get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {email} not found")
    if user.role == "owner" and user.is_active and count_active_owners() <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove the last active owner")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM share_users WHERE email = %s", (email,))
        conn.commit()


def list_users() -> list[AccessUser]:
    """List access users."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT email, role, is_active, created_at, updated_at
            FROM share_users
            ORDER BY role, email
            """
        )
        rows = cur.fetchall()
    return [
        AccessUser(
            email=row[0],
            role=row[1],
            is_active=row[2],
            created_at=row[3],
            updated_at=row[4],
        )
        for row in rows
    ]


def list_user_grants(email: str) -> list[AccessGrant]:
    """List grants for one user."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT user_email, project_id, section, created_at
            FROM share_grants
            WHERE user_email = %s
            ORDER BY project_id, section
            """,
            (normalize_email(email),),
        )
        rows = cur.fetchall()
    return [
        AccessGrant(
            user_email=row[0],
            project_id=row[1],
            section=row[2],
            created_at=row[3],
        )
        for row in rows
    ]


def list_all_grants() -> list[AccessGrant]:
    """List all grants."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT user_email, project_id, section, created_at
            FROM share_grants
            ORDER BY user_email, project_id, section
            """
        )
        rows = cur.fetchall()
    return [
        AccessGrant(
            user_email=row[0],
            project_id=row[1],
            section=row[2],
            created_at=row[3],
        )
        for row in rows
    ]


def set_project_grants(email: str, project_id: str, sections: list[str]) -> list[AccessGrant]:
    """Replace one user's grants for a project."""
    email = normalize_email(email)
    unknown_sections = sorted(set(sections) - ACCESS_SECTIONS)
    if unknown_sections:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported section(s): {', '.join(unknown_sections)}",
        )
    user = get_user(email)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {email} not found")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        cur.execute(
            "DELETE FROM share_grants WHERE user_email = %s AND project_id = %s",
            (email, project_id),
        )
        for section in sorted(set(sections)):
            cur.execute(
                """
                INSERT INTO share_grants (user_email, project_id, section)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (email, project_id, section),
            )
        conn.commit()
    return list_user_grants(email)


def has_project_section_access(email: str, project_id: str, section: str) -> bool:
    """Return whether an active user can view a project section."""
    if section not in ACCESS_SECTIONS:
        return False
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM share_users users
            JOIN share_grants grants ON grants.user_email = users.email
            WHERE users.email = %s
              AND users.is_active = TRUE
              AND users.role = 'viewer'
              AND grants.project_id = %s
              AND grants.section = %s
            """,
            (normalize_email(email), project_id, section),
        )
        return cur.fetchone() is not None


def list_viewer_projects(email: str) -> list[dict[str, object]]:
    """List projects and sections visible to a viewer."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.name, p.public_url, p.created_at, array_agg(g.section ORDER BY g.section)
            FROM share_grants g
            JOIN projects p ON p.id = g.project_id
            JOIN share_users u ON u.email = g.user_email
            WHERE g.user_email = %s
              AND u.is_active = TRUE
              AND u.role = 'viewer'
            GROUP BY p.id, p.name, p.public_url, p.created_at
            ORDER BY p.name
            """,
            (normalize_email(email),),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "public_url": row[2],
            "created_at": row[3],
            "sections": row[4] or [],
        }
        for row in rows
    ]
