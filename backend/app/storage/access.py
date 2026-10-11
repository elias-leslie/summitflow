"""Owner identity persistence for SummitFlow access control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .connection import get_connection, get_cursor


@dataclass(frozen=True)
class AccessUser:
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


def normalize_email(value: str) -> str:
    """Return a canonical email address for identity lookups."""
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
