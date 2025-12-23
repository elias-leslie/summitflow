"""Storage layer for extraction prompts.

Manages customizable prompts used for extracting TDD specs from roundtable
conversations. Each project can have custom prompts that override the defaults.

Note: Default TDD spec extraction prompts are defined in roundtable service.
This module handles custom prompt storage/retrieval only.
"""

from typing import Any

from .connection import get_connection

# Default prompts - empty after Vision/Goals/Features removal.
# TDD spec extraction prompts are defined in roundtable service.
DEFAULT_PROMPTS: dict[str, dict[str, Any]] = {}


def get_default_prompts() -> dict[str, dict[str, Any]]:
    """Get all default prompts.

    Returns:
        Dict mapping prompt_type to prompt configuration
    """
    return DEFAULT_PROMPTS.copy()


def get_extraction_prompt(
    project_id: str,
    prompt_type: str,
) -> dict[str, Any] | None:
    """Get an extraction prompt for a project.

    Returns custom prompt if exists, otherwise returns default.

    Args:
        project_id: Project ID
        prompt_type: Type of prompt (feature_extraction, vision_extraction, goals_extraction)

    Returns:
        Prompt configuration dict or None if no default exists
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT prompt_type, prompt_text, primary_agent, primary_model,
                   verification_enabled, verification_agent, verification_model,
                   verification_prompt, created_at, updated_at
            FROM extraction_prompts
            WHERE project_id = %s AND prompt_type = %s
            """,
            (project_id, prompt_type),
        )
        row = cur.fetchone()

    if row:
        return {
            "prompt_type": row[0],
            "prompt_text": row[1],
            "primary_agent": row[2],
            "primary_model": row[3],
            "verification_enabled": row[4],
            "verification_agent": row[5],
            "verification_model": row[6],
            "verification_prompt": row[7],
            "created_at": row[8],
            "updated_at": row[9],
            "is_default": False,
        }

    # Return default if no custom prompt
    default = DEFAULT_PROMPTS.get(prompt_type)
    if default:
        return {**default, "is_default": True}

    return None


def get_all_extraction_prompts(project_id: str) -> list[dict[str, Any]]:
    """Get all extraction prompts for a project.

    Returns custom prompts merged with defaults (custom takes precedence).

    Args:
        project_id: Project ID

    Returns:
        List of prompt configuration dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT prompt_type, prompt_text, primary_agent, primary_model,
                   verification_enabled, verification_agent, verification_model,
                   verification_prompt, created_at, updated_at
            FROM extraction_prompts
            WHERE project_id = %s
            """,
            (project_id,),
        )
        rows = cur.fetchall()

    # Build dict of custom prompts
    custom_prompts = {}
    for row in rows:
        custom_prompts[row[0]] = {
            "prompt_type": row[0],
            "prompt_text": row[1],
            "primary_agent": row[2],
            "primary_model": row[3],
            "verification_enabled": row[4],
            "verification_agent": row[5],
            "verification_model": row[6],
            "verification_prompt": row[7],
            "created_at": row[8],
            "updated_at": row[9],
            "is_default": False,
        }

    # Merge with defaults
    result = []
    for prompt_type, default in DEFAULT_PROMPTS.items():
        if prompt_type in custom_prompts:
            result.append(custom_prompts[prompt_type])
        else:
            result.append({**default, "is_default": True})

    return result


def upsert_extraction_prompt(
    project_id: str,
    prompt_type: str,
    prompt_text: str,
    primary_agent: str = "claude",
    primary_model: str = "claude-sonnet-4-5",
    verification_enabled: bool = False,
    verification_agent: str | None = None,
    verification_model: str | None = None,
    verification_prompt: str | None = None,
) -> dict[str, Any]:
    """Create or update an extraction prompt.

    Args:
        project_id: Project ID
        prompt_type: Type of prompt
        prompt_text: The prompt text
        primary_agent: Agent to use (claude/gemini)
        primary_model: Model ID to use
        verification_enabled: Enable second-pass verification
        verification_agent: Agent for verification
        verification_model: Model for verification
        verification_prompt: Prompt for verification pass

    Returns:
        Saved prompt configuration dict
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO extraction_prompts
                (project_id, prompt_type, prompt_text, primary_agent, primary_model,
                 verification_enabled, verification_agent, verification_model,
                 verification_prompt, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (project_id, prompt_type) DO UPDATE SET
                prompt_text = EXCLUDED.prompt_text,
                primary_agent = EXCLUDED.primary_agent,
                primary_model = EXCLUDED.primary_model,
                verification_enabled = EXCLUDED.verification_enabled,
                verification_agent = EXCLUDED.verification_agent,
                verification_model = EXCLUDED.verification_model,
                verification_prompt = EXCLUDED.verification_prompt,
                updated_at = NOW()
            RETURNING prompt_type, prompt_text, primary_agent, primary_model,
                      verification_enabled, verification_agent, verification_model,
                      verification_prompt, created_at, updated_at
            """,
            (
                project_id,
                prompt_type,
                prompt_text,
                primary_agent,
                primary_model,
                verification_enabled,
                verification_agent,
                verification_model,
                verification_prompt,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return {
        "prompt_type": row[0],
        "prompt_text": row[1],
        "primary_agent": row[2],
        "primary_model": row[3],
        "verification_enabled": row[4],
        "verification_agent": row[5],
        "verification_model": row[6],
        "verification_prompt": row[7],
        "created_at": row[8],
        "updated_at": row[9],
        "is_default": False,
    }


def delete_extraction_prompt(
    project_id: str,
    prompt_type: str,
) -> bool:
    """Delete a custom extraction prompt (revert to default).

    Args:
        project_id: Project ID
        prompt_type: Type of prompt

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM extraction_prompts
            WHERE project_id = %s AND prompt_type = %s
            RETURNING id
            """,
            (project_id, prompt_type),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None
