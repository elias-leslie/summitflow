"""Helper functions for Ideas API."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from ..storage.connection import get_connection

# Rate limiting constants
MAX_IDEAS_PER_USER_PER_HOUR = 5
ESTIMATED_COST_PER_REFINEMENT = 0.002  # ~$0.002 for Gemini Flash (refine + score)
DEFAULT_DAILY_BUDGET_USD = 5.0


def get_project_daily_budget(project_id: str) -> float:
    """Get the daily budget for a project from automation settings."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT automation_settings FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return float(row[0].get("daily_budget_usd", DEFAULT_DAILY_BUDGET_USD))
        return DEFAULT_DAILY_BUDGET_USD


def check_rate_limit(project_id: str, user_identifier: str) -> None:
    """Check if user/project has exceeded rate limits.

    Uses project's daily_budget_usd from automation settings.
    Raises HTTPException 429 if limits exceeded.
    """
    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with get_connection() as conn, conn.cursor() as cur:
        # Check per-user hourly limit (only for identified users)
        if user_identifier and user_identifier != "anonymous":
            cur.execute(
                """
                SELECT COUNT(*) FROM ideas
                WHERE user_email = %s
                AND created_at > %s
                AND project_id = %s
                """,
                (user_identifier, hour_ago, project_id),
            )
            row = cur.fetchone()
            user_count = row[0] if row else 0

            if user_count >= MAX_IDEAS_PER_USER_PER_HOUR:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {MAX_IDEAS_PER_USER_PER_HOUR} ideas per hour.",
                )

        # Check project daily budget
        cur.execute(
            """
            SELECT COUNT(*) FROM ideas
            WHERE project_id = %s
            AND created_at > %s
            AND status IN ('refined', 'approved', 'rejected', 'executing', 'completed')
            """,
            (project_id, day_start),
        )
        row = cur.fetchone()
        daily_refinements = row[0] if row else 0

    # Calculate cost and check against budget
    daily_cost = daily_refinements * ESTIMATED_COST_PER_REFINEMENT
    daily_budget = get_project_daily_budget(project_id)

    if daily_cost >= daily_budget:
        raise HTTPException(
            status_code=429,
            detail=f"Daily budget exhausted (${daily_cost:.2f}/${daily_budget:.2f}). Try again tomorrow.",
        )


def extract_email_from_cf_jwt(jwt_assertion: str | None) -> str | None:
    """Extract email from Cloudflare Access JWT.

    CF Access JWT is base64 encoded with 3 parts: header.payload.signature
    Payload contains 'email' field.
    """
    if not jwt_assertion:
        return None
    try:
        parts = jwt_assertion.split(".")
        if len(parts) != 3:
            return None
        # Add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)
        email = data.get("email")
        return str(email) if email is not None else None
    except Exception:
        return None
