"""Storage layer for prompts.

Manages customizable prompts used for TDD specs, recovery, QA, and extraction.
Each project can have custom prompts that override the defaults.
"""

from typing import Any

from .connection import get_connection

# Default prompts for spec pipeline, recovery, and QA
DEFAULT_PROMPTS: dict[str, dict[str, Any]] = {
    # ==============================
    # Spec Pipeline Prompts
    # ==============================
    "spec_context_discovery": {
        "prompt_type": "spec_context_discovery",
        "prompt_text": """You are analyzing a codebase to discover context for implementing a feature.

Given the feature description and existing codebase patterns, identify:
1. Relevant existing files and modules
2. Patterns to follow (naming, structure, dependencies)
3. Integration points (APIs, services, utilities to use)
4. Potential conflicts or considerations

Output a structured analysis that will help guide the implementation.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "spec",
        "thinking_budget": 5000,
        "tools_enabled": ["read_file", "glob", "grep"],
    },
    "spec_requirements_enhance": {
        "prompt_type": "spec_requirements_enhance",
        "prompt_text": """You are enhancing a feature specification with implementation details.

Given the initial requirements and codebase context, enhance the spec with:
1. Specific files to create/modify
2. Function signatures and interfaces
3. Data models and schemas
4. Test requirements
5. Edge cases to handle

Output a detailed implementation specification.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "spec",
        "thinking_budget": 5000,
        "tools_enabled": [],
    },
    "spec_self_critique": {
        "prompt_type": "spec_self_critique",
        "prompt_text": """You are critically reviewing a feature specification for completeness and correctness.

Analyze the spec for:
1. Missing requirements or edge cases
2. Inconsistencies or contradictions
3. Unclear or ambiguous statements
4. Potential implementation issues
5. Security or performance concerns

Provide specific improvements and flag any blocking issues.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "spec",
        "thinking_budget": 20000,
        "tools_enabled": [],
    },
    "spec_implementation_plan": {
        "prompt_type": "spec_implementation_plan",
        "prompt_text": """You are creating a step-by-step implementation plan from a feature specification.

Generate:
1. Ordered list of implementation tasks
2. Dependencies between tasks
3. Verification steps for each task
4. Rollback considerations
5. Estimated complexity per task

Output a JSON implementation plan compatible with the task system.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "spec",
        "thinking_budget": 10000,
        "tools_enabled": [],
    },
    # ==============================
    # Recovery Prompts
    # ==============================
    "recovery_classify_failure": {
        "prompt_type": "recovery_classify_failure",
        "prompt_text": """You are classifying a test or build failure to determine the recovery strategy.

Given the error output, classify it as:
1. syntax_error - Fix syntax issues
2. type_error - Fix type mismatches
3. import_error - Fix missing imports or circular deps
4. test_failure - Fix failing assertions
5. runtime_error - Fix runtime exceptions
6. unknown - Requires manual investigation

Output the classification and affected file(s).""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "recovery",
        "thinking_budget": 0,
        "tools_enabled": [],
    },
    "recovery_fix_code": {
        "prompt_type": "recovery_fix_code",
        "prompt_text": """You are fixing code based on a classified failure.

Given:
- The failure type and error message
- The affected file(s)
- The original code

Generate the fix:
1. Identify the root cause
2. Provide the corrected code
3. Explain the fix
4. Suggest any related fixes needed

Output the fix as a code diff or replacement.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "recovery",
        "thinking_budget": 10000,
        "tools_enabled": ["read_file", "write_file"],
    },
    # ==============================
    # QA Prompts
    # ==============================
    "qa_review": {
        "prompt_type": "qa_review",
        "prompt_text": """You are reviewing implemented code for quality assurance.

Check for:
1. Code correctness and logic errors
2. Edge cases not handled
3. Security vulnerabilities
4. Performance issues
5. Code style and consistency
6. Documentation completeness

Output a structured QA report with severity levels.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "qa",
        "thinking_budget": 5000,
        "tools_enabled": ["read_file"],
    },
    "qa_fix": {
        "prompt_type": "qa_fix",
        "prompt_text": """You are fixing issues identified in a QA review.

Given:
- The QA report with issues
- The affected code

For each issue:
1. Confirm the issue exists
2. Provide the fix
3. Verify the fix doesn't introduce new issues
4. Update related documentation if needed

Output the fixes as code diffs.""",
        "primary_agent": "claude",
        "primary_model": "claude-sonnet-4-5",
        "verification_enabled": False,
        "category": "qa",
        "thinking_budget": 10000,
        "tools_enabled": ["read_file", "write_file"],
    },
}


def get_default_prompts() -> dict[str, dict[str, Any]]:
    """Get all default prompts.

    Returns:
        Dict mapping prompt_type to prompt configuration
    """
    return DEFAULT_PROMPTS.copy()


def get_prompt(
    project_id: str,
    prompt_type: str,
) -> dict[str, Any] | None:
    """Get a prompt for a project.

    Returns custom prompt if exists, otherwise returns default.

    Args:
        project_id: Project ID
        prompt_type: Type of prompt

    Returns:
        Prompt configuration dict or None if no default exists
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT prompt_type, prompt_text, primary_agent, primary_model,
                   verification_enabled, verification_agent, verification_model,
                   verification_prompt, category, thinking_budget, tools_enabled,
                   created_at, updated_at
            FROM prompts
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
            "category": row[8],
            "thinking_budget": row[9],
            "tools_enabled": row[10] or [],
            "created_at": row[11],
            "updated_at": row[12],
            "is_default": False,
        }

    # Return default if no custom prompt
    default = DEFAULT_PROMPTS.get(prompt_type)
    if default:
        return {**default, "is_default": True}

    return None


# Alias for backward compatibility
get_extraction_prompt = get_prompt


def get_all_prompts(
    project_id: str,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Get all prompts for a project.

    Returns custom prompts merged with defaults (custom takes precedence).

    Args:
        project_id: Project ID
        category: Optional filter by category (spec, recovery, qa, extraction)

    Returns:
        List of prompt configuration dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        if category:
            cur.execute(
                """
                SELECT prompt_type, prompt_text, primary_agent, primary_model,
                       verification_enabled, verification_agent, verification_model,
                       verification_prompt, category, thinking_budget, tools_enabled,
                       created_at, updated_at
                FROM prompts
                WHERE project_id = %s AND category = %s
                """,
                (project_id, category),
            )
        else:
            cur.execute(
                """
                SELECT prompt_type, prompt_text, primary_agent, primary_model,
                       verification_enabled, verification_agent, verification_model,
                       verification_prompt, category, thinking_budget, tools_enabled,
                       created_at, updated_at
                FROM prompts
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
            "category": row[8],
            "thinking_budget": row[9],
            "tools_enabled": row[10] or [],
            "created_at": row[11],
            "updated_at": row[12],
            "is_default": False,
        }

    # Merge with defaults (filtered by category if specified)
    result = []
    for prompt_type, default in DEFAULT_PROMPTS.items():
        if category and default.get("category") != category:
            continue
        if prompt_type in custom_prompts:
            result.append(custom_prompts[prompt_type])
        else:
            result.append({**default, "is_default": True})

    # Add any custom prompts not in defaults
    for prompt_type, prompt in custom_prompts.items():
        if prompt_type not in DEFAULT_PROMPTS and (
            not category or prompt.get("category") == category
        ):
            result.append(prompt)

    return result


# Alias for backward compatibility
get_all_extraction_prompts = get_all_prompts


def upsert_prompt(
    project_id: str,
    prompt_type: str,
    prompt_text: str,
    primary_agent: str = "claude",
    primary_model: str = "claude-sonnet-4-5",
    verification_enabled: bool = False,
    verification_agent: str | None = None,
    verification_model: str | None = None,
    verification_prompt: str | None = None,
    category: str = "extraction",
    thinking_budget: int = 0,
    tools_enabled: list[str] | None = None,
) -> dict[str, Any]:
    """Create or update a prompt.

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
        category: Prompt category (spec, recovery, qa, extraction)
        thinking_budget: Token budget for extended thinking
        tools_enabled: List of enabled tool names

    Returns:
        Saved prompt configuration dict
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompts
                (project_id, prompt_type, prompt_text, primary_agent, primary_model,
                 verification_enabled, verification_agent, verification_model,
                 verification_prompt, category, thinking_budget, tools_enabled,
                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (project_id, prompt_type) DO UPDATE SET
                prompt_text = EXCLUDED.prompt_text,
                primary_agent = EXCLUDED.primary_agent,
                primary_model = EXCLUDED.primary_model,
                verification_enabled = EXCLUDED.verification_enabled,
                verification_agent = EXCLUDED.verification_agent,
                verification_model = EXCLUDED.verification_model,
                verification_prompt = EXCLUDED.verification_prompt,
                category = EXCLUDED.category,
                thinking_budget = EXCLUDED.thinking_budget,
                tools_enabled = EXCLUDED.tools_enabled,
                updated_at = NOW()
            RETURNING prompt_type, prompt_text, primary_agent, primary_model,
                      verification_enabled, verification_agent, verification_model,
                      verification_prompt, category, thinking_budget, tools_enabled,
                      created_at, updated_at
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
                category,
                thinking_budget,
                tools_enabled or [],
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
        "category": row[8],
        "thinking_budget": row[9],
        "tools_enabled": row[10] or [],
        "created_at": row[11],
        "updated_at": row[12],
        "is_default": False,
    }


# Alias for backward compatibility
upsert_extraction_prompt = upsert_prompt


def delete_prompt(
    project_id: str,
    prompt_type: str,
) -> bool:
    """Delete a custom prompt (revert to default).

    Args:
        project_id: Project ID
        prompt_type: Type of prompt

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM prompts
            WHERE project_id = %s AND prompt_type = %s
            RETURNING id
            """,
            (project_id, prompt_type),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None


# Alias for backward compatibility
delete_extraction_prompt = delete_prompt
