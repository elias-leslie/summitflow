"""Fix agent for lint/type errors.

Uses 3-2-1 escalation pattern:
- WORKER (3 attempts): GEMINI_FLASH
- SUPERVISOR (2 attempts): CLAUDE_SONNET with different strategy
- HUMAN: Create blocking task for manual review
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Literal

import psycopg

from ...constants import CLAUDE_SONNET, GEMINI_FLASH
from ...logging_config import get_logger
from ...services.agent_hub_client import AgentType, get_agent
from ...storage import quality_check_results as qcr_store
from ...storage.projects import get_project_root_path

logger = get_logger(__name__)

FixResult = Literal["fixed", "failed", "escalated_supervisor", "escalated_human"]

# 3-2-1 escalation thresholds
WORKER_ATTEMPTS = 3  # Attempts 1-3
SUPERVISOR_ATTEMPTS = 2  # Attempts 4-5
MAX_FIX_ATTEMPTS = WORKER_ATTEMPTS + SUPERVISOR_ATTEMPTS  # 5 total before HUMAN


def get_escalation_level(attempts: int) -> str:
    """Get current escalation level based on attempt count.

    Args:
        attempts: Number of fix attempts made

    Returns:
        'WORKER', 'SUPERVISOR', or 'HUMAN'
    """
    if attempts < WORKER_ATTEMPTS:
        return "WORKER"
    elif attempts < MAX_FIX_ATTEMPTS:
        return "SUPERVISOR"
    else:
        return "HUMAN"


def _read_file_content(file_path: Path, context_lines: int = 10) -> str | None:
    """Read file content with surrounding context.

    Args:
        file_path: Path to file
        context_lines: Number of lines of context to include around error

    Returns:
        File content or None if file doesn't exist
    """
    if not file_path.exists():
        return None
    try:
        return file_path.read_text()
    except Exception as e:
        logger.warning("read_file_failed", path=str(file_path), error=str(e))
        return None


def _build_fix_prompt(
    check_result: dict[str, Any],
    file_content: str,
    project_path: Path,
) -> str:
    """Build prompt for fix agent.

    Args:
        check_result: Quality check result from DB
        file_content: Content of the file with the error
        project_path: Path to project root

    Returns:
        Prompt string for the LLM
    """
    check_type = check_result["check_type"]
    error_message = check_result.get("error_message", "")
    file_path = check_result.get("file_path", "")
    line_number = check_result.get("line_number")
    check_name = check_result.get("check_name", "")

    lines = [
        f"# Fix {check_type.upper()} Error",
        "",
        f"**File:** {file_path}",
    ]
    if line_number:
        lines.append(f"**Line:** {line_number}")
    if check_name:
        lines.append(f"**Rule/Check:** {check_name}")
    lines.extend(
        [
            "",
            "**Error Message:**",
            "```",
            error_message,
            "```",
            "",
            "**Current File Content:**",
            "```python" if file_path.endswith(".py") else "```",
            file_content,
            "```",
            "",
            "## Instructions",
            "",
        ]
    )

    if check_type == "ruff":
        lines.extend(
            [
                "Fix the ruff linting error. Common fixes:",
                "- F401: Remove unused import",
                "- E501: Break long line (use parentheses or line continuation)",
                "- W291/W293: Remove trailing whitespace",
                "- E302/E303: Fix blank lines around functions/classes",
                "- F841: Remove unused variable or prefix with underscore",
                "",
            ]
        )
    elif check_type == "mypy":
        lines.extend(
            [
                "Fix the mypy type error. Common fixes:",
                "- Add type annotations",
                "- Add proper None checks",
                "- Use cast() or type guards",
                "- Fix return type annotations",
                "- Import types from typing module",
                "",
            ]
        )
    elif check_type == "biome":
        lines.extend(
            [
                "Fix the Biome lint/format error. Common fixes:",
                "- Fix import order",
                "- Add missing semicolons",
                "- Fix unused variables",
                "- Apply consistent formatting",
                "",
            ]
        )
    elif check_type == "tsc":
        lines.extend(
            [
                "Fix the TypeScript type error. Common fixes:",
                "- Add proper type annotations",
                "- Fix type mismatches",
                "- Handle undefined/null properly",
                "- Import missing types",
                "",
            ]
        )

    lines.extend(
        [
            "## Response Format",
            "",
            "Respond with ONLY the fixed file content, no explanation.",
            "If you cannot fix the error, respond with exactly: CANNOT_FIX: <reason>",
            "",
            "Do not include markdown code fences in your response.",
        ]
    )

    return "\n".join(lines)


def _apply_fix(file_path: Path, new_content: str) -> bool:
    """Apply the fix to the file.

    Args:
        file_path: Path to file
        new_content: New file content

    Returns:
        True if fix was applied successfully
    """
    try:
        file_path.write_text(new_content)
        return True
    except Exception as e:
        logger.error("apply_fix_failed", path=str(file_path), error=str(e))
        return False


def _verify_fix(
    project_path: Path,
    check_type: str,
    file_path: str,
) -> bool:
    """Re-run the check to verify the fix worked.

    Args:
        project_path: Path to project root
        check_type: Type of check (ruff, mypy, biome, tsc)
        file_path: Path to the fixed file

    Returns:
        True if the check now passes
    """
    cmd: list[str] = []
    cwd = project_path

    if check_type == "ruff":
        cmd = ["ruff", "check", file_path, "--quiet"]
    elif check_type == "mypy":
        cmd = ["mypy", file_path, "--no-error-summary", "--quiet"]
    elif check_type == "biome":
        cmd = ["npx", "biome", "check", file_path, "--quiet"]
    elif check_type == "tsc":
        # For tsc we check the whole project since it needs tsconfig context
        cmd = ["npx", "tsc", "--noEmit"]
    else:
        logger.warning("unknown_check_type", check_type=check_type)
        return False

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("verify_timeout", check_type=check_type, file=file_path)
        return False
    except Exception as e:
        logger.error("verify_failed", check_type=check_type, error=str(e))
        return False


def fix_lint_type_error(
    conn: psycopg.Connection[Any],
    result_id: int,
) -> FixResult:
    """Attempt to fix a lint/type error using 3-2-1 escalation.

    - WORKER (3 attempts): Uses GEMINI_FLASH
    - SUPERVISOR (2 attempts): Uses CLAUDE_SONNET with enhanced prompt
    - HUMAN: Returns escalated_human for task creation

    Args:
        conn: Database connection
        result_id: ID of the quality_check_result to fix

    Returns:
        FixResult: "fixed", "failed", "escalated_supervisor", or "escalated_human"
    """
    check_result = qcr_store.get_check_result(conn, result_id)
    if not check_result:
        logger.error("check_result_not_found", result_id=result_id)
        return "failed"

    # Only handle lint/type errors
    check_type = check_result["check_type"]
    if check_type not in ("ruff", "mypy", "biome", "tsc"):
        logger.warning("unsupported_check_type", check_type=check_type)
        return "failed"

    # Check if already fixed
    if check_result.get("fixed_at"):
        logger.info("already_fixed", result_id=result_id)
        return "fixed"

    # Check escalation level
    attempts = check_result.get("fix_attempts", 0)
    level = get_escalation_level(attempts)

    if level == "HUMAN":
        logger.info(
            "escalated_to_human",
            result_id=result_id,
            attempts=attempts,
        )
        return "escalated_human"

    # Get project path
    project_id = check_result["project_id"]
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("project_not_found", project_id=project_id)
        return "failed"
    project_path = Path(root_path)

    # Get file path
    file_rel_path = check_result.get("file_path")
    if not file_rel_path:
        logger.warning("no_file_path", result_id=result_id)
        return "failed"

    file_path = project_path / file_rel_path
    file_content = _read_file_content(file_path)
    if not file_content:
        logger.warning("file_not_found", path=str(file_path))
        return "failed"

    # Record attempt
    qcr_store.record_fix_attempt(conn, result_id)

    # Build prompt - enhanced for SUPERVISOR level
    prompt = _build_fix_prompt(check_result, file_content, project_path)
    if level == "SUPERVISOR":
        prompt = f"""Previous fix attempts have failed. Try a different approach.

{prompt}

IMPORTANT: Previous attempts failed. Consider:
- Reading surrounding context more carefully
- The error might require structural changes, not just line fixes
- Check if imports or dependencies are missing
- Verify the fix actually addresses the root cause
"""

    # Select model based on escalation level
    provider: AgentType
    if level == "WORKER":
        model = GEMINI_FLASH
        provider = "gemini"
    else:  # SUPERVISOR
        model = CLAUDE_SONNET
        provider = "claude"

    logger.info(
        "fix_attempt",
        result_id=result_id,
        level=level,
        attempt=attempts + 1,
        model=model,
    )

    try:
        agent = get_agent(provider, model=model)
        response = agent.generate(
            prompt=prompt,
            system="You are a code fix agent. Output only the fixed code, no explanations.",
            max_tokens=8000,
            temperature=0.2 if level == "WORKER" else 0.3,
            purpose="quality_gate_fix",
        )
        new_content = response.content.strip()
    except Exception as e:
        logger.error("llm_failed", error=str(e))
        return "failed"

    # Check for cannot fix response
    if new_content.startswith("CANNOT_FIX:"):
        reason = new_content[11:].strip()
        logger.info("cannot_fix", result_id=result_id, reason=reason)
        return "failed"

    # Apply the fix
    if not _apply_fix(file_path, new_content):
        return "failed"

    # Verify the fix worked
    if _verify_fix(project_path, check_type, file_rel_path):
        fixed_by = "gemini-flash" if level == "WORKER" else "claude-sonnet"
        qcr_store.mark_fixed(conn, result_id, fixed_by=fixed_by)
        logger.info("fix_successful", result_id=result_id, check_type=check_type, model=fixed_by)
        return "fixed"
    else:
        logger.info("fix_did_not_pass", result_id=result_id)
        # Check if we should escalate
        updated = qcr_store.get_check_result(conn, result_id)
        if updated and updated.get("fix_attempts", 0) >= MAX_FIX_ATTEMPTS:
            return "escalated_human"
        elif level == "WORKER" and updated and updated.get("fix_attempts", 0) >= WORKER_ATTEMPTS:
            return "escalated_supervisor"
        return "failed"


def fix_unfixed_errors(
    conn: psycopg.Connection[Any],
    project_id: str,
    check_type: qcr_store.CheckType | None = None,
    limit: int = 10,
) -> dict[str, int]:
    """Fix all unfixed lint/type errors for a project.

    Args:
        conn: Database connection
        project_id: Project ID
        check_type: Optional filter by check type
        limit: Maximum number of errors to attempt

    Returns:
        Dict with counts: fixed, failed, escalated
    """
    results = {"fixed": 0, "failed": 0, "escalated": 0}

    # Get unfixed results
    unfixed = qcr_store.list_check_results(
        conn,
        project_id,
        check_type=check_type,
        unfixed_only=True,
        limit=limit,
    )

    # Filter to lint/type errors only
    lint_type_errors = [r for r in unfixed if r["check_type"] in ("ruff", "mypy", "biome", "tsc")]

    for result in lint_type_errors:
        outcome = fix_lint_type_error(conn, result["id"])
        # Map escalated_supervisor and escalated_human to escalated
        if outcome in ("escalated_supervisor", "escalated_human"):
            results["escalated"] += 1
        else:
            results[outcome] += 1

    logger.info(
        "batch_fix_complete",
        project_id=project_id,
        **results,
    )

    return results
