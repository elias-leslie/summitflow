"""Fix agent for test failures.

Uses CLAUDE_SONNET for test failure fixes since tests require more
complex reasoning about expected vs actual behavior.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Literal

import psycopg

from ...logging_config import get_logger
from ...services.agent_hub_client import get_agent
from ...storage import quality_check_results as qcr_store
from ...storage.projects import get_project_root_path
from .escalation import escalate_to_supervisor

logger = get_logger(__name__)

TestFixResult = Literal["fixed", "failed", "escalated"]

MAX_FIX_ATTEMPTS = 3


def _read_file_content(file_path: Path) -> str | None:
    """Read file content.

    Args:
        file_path: Path to file

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


def _find_test_subject(test_file: Path, project_path: Path) -> Path | None:
    """Find the source file being tested.

    Uses convention: test_foo.py -> foo.py

    Args:
        test_file: Path to the test file
        project_path: Project root path

    Returns:
        Path to source file or None
    """
    test_name = test_file.stem  # e.g., "test_foo"
    if test_name.startswith("test_"):
        source_name = test_name[5:] + ".py"  # e.g., "foo.py"

        # Look in common source directories
        candidates = [
            project_path / "app" / source_name,
            project_path / "src" / source_name,
            project_path / source_name,
        ]

        # Also check same directory structure minus "tests" dir
        rel_path = test_file.relative_to(project_path)
        parts = list(rel_path.parts)
        if "tests" in parts:
            test_idx = parts.index("tests")
            source_parts = parts[:test_idx] + parts[test_idx + 1 :]
            source_parts[-1] = source_name
            candidates.append(project_path / Path(*source_parts))

        for candidate in candidates:
            if candidate.exists():
                return candidate

    return None


def _build_test_fix_prompt(
    check_result: dict[str, Any],
    test_file_content: str,
    source_file_content: str | None,
    project_path: Path,
) -> str:
    """Build prompt for test fix agent.

    Args:
        check_result: Quality check result from DB
        test_file_content: Content of the test file
        source_file_content: Content of the source file (if found)
        project_path: Path to project root

    Returns:
        Prompt string for the LLM
    """
    error_message = check_result.get("error_message", "")
    file_path = check_result.get("file_path", "")
    check_name = check_result.get("check_name", "")  # Test function name

    lines = [
        "# Fix Test Failure",
        "",
        f"**Test File:** {file_path}",
    ]
    if check_name:
        lines.append(f"**Failing Test:** {check_name}")
    lines.extend(
        [
            "",
            "**Failure Output:**",
            "```",
            error_message,
            "```",
            "",
            "**Test File Content:**",
            "```python",
            test_file_content,
            "```",
            "",
        ]
    )

    if source_file_content:
        lines.extend(
            [
                "**Source Code Being Tested:**",
                "```python",
                source_file_content,
                "```",
                "",
            ]
        )

    lines.extend(
        [
            "## Instructions",
            "",
            "Analyze the test failure and determine if the issue is:",
            "1. A bug in the source code (fix the source)",
            "2. An incorrect test expectation (fix the test)",
            "3. A missing mock or fixture (add it)",
            "",
            "## Response Format",
            "",
            "Respond with a JSON object:",
            "```json",
            "{",
            '  "fix_type": "source" | "test",',
            '  "file_to_fix": "relative/path/to/file.py",',
            '  "fixed_content": "full file content here",',
            '  "explanation": "brief explanation of the fix"',
            "}",
            "```",
            "",
            "If you cannot fix the error, respond with:",
            "```json",
            '{"fix_type": "cannot_fix", "reason": "explanation"}',
            "```",
        ]
    )

    return "\n".join(lines)


def _parse_test_fix_response(response_text: str) -> dict[str, Any]:
    """Parse the fix response from the LLM.

    Args:
        response_text: Raw response text

    Returns:
        Parsed fix dict with fix_type, file_to_fix, fixed_content
    """
    import json
    import re

    # Try to extract JSON from response
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
        try:
            parsed: dict[str, Any] = json.loads(json_str)
            return parsed
        except json.JSONDecodeError as e:
            return {
                "fix_type": "cannot_fix",
                "reason": f"JSON parse error: {e}",
            }

    # Try balanced JSON extraction via raw_decode (handles nested braces)
    decoder = json.JSONDecoder()
    brace_idx = response_text.find("{")
    if brace_idx == -1:
        return {
            "fix_type": "cannot_fix",
            "reason": "Could not parse response format",
        }
    try:
        parsed, _ = decoder.raw_decode(response_text, brace_idx)
        return parsed
    except json.JSONDecodeError as e:
        return {
            "fix_type": "cannot_fix",
            "reason": f"JSON parse error: {e}",
        }


def _verify_test(
    project_path: Path,
    test_name: str | None,
) -> bool:
    """Re-run the test to verify the fix worked.

    Args:
        project_path: Path to project root
        test_name: Optional specific test to run

    Returns:
        True if the test now passes
    """
    cmd = ["pytest", "-xvs"]
    if test_name:
        cmd.extend(["-k", test_name])

    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning("test_verify_timeout", test_name=test_name)
        return False
    except Exception as e:
        logger.error("test_verify_failed", error=str(e))
        return False


def fix_test_failure(
    conn: psycopg.Connection[Any],
    result_id: int,
) -> TestFixResult:
    """Attempt to fix a test failure.

    Uses CLAUDE_SONNET to analyze the failure and generate a fix.
    May fix either the test or the source code.

    Args:
        conn: Database connection
        result_id: ID of the quality_check_result to fix

    Returns:
        TestFixResult: "fixed", "failed", or "escalated"
    """
    check_result = qcr_store.get_check_result(conn, result_id)
    if not check_result:
        logger.error("check_result_not_found", result_id=result_id)
        return "failed"

    # Only handle test failures
    if check_result["check_type"] != "pytest":
        logger.warning("not_a_test_failure", check_type=check_result["check_type"])
        return "failed"

    # Check if already fixed
    if check_result.get("fixed_at"):
        logger.info("already_fixed", result_id=result_id)
        return "fixed"

    # Check attempt count
    attempts = check_result.get("fix_attempts", 0)
    if attempts >= MAX_FIX_ATTEMPTS:
        logger.info("max_attempts_reached", result_id=result_id, attempts=attempts)
        # Create blocking task for manual review
        escalate_to_supervisor(conn, result_id)
        return "escalated"

    # Get project path
    project_id = check_result["project_id"]
    root_path = get_project_root_path(project_id)
    if not root_path:
        logger.error("project_not_found", project_id=project_id)
        return "failed"
    project_path = Path(root_path)

    # Get test file path
    test_rel_path = check_result.get("file_path")
    if not test_rel_path:
        logger.warning("no_file_path", result_id=result_id)
        return "failed"

    test_file = project_path / test_rel_path
    test_content = _read_file_content(test_file)
    if not test_content:
        logger.warning("test_file_not_found", path=str(test_file))
        return "failed"

    # Try to find source file
    source_file = _find_test_subject(test_file, project_path)
    source_content = _read_file_content(source_file) if source_file else None

    # Record attempt
    qcr_store.record_fix_attempt(conn, result_id)
    current_attempts = attempts + 1

    # Build prompt and call LLM
    prompt = _build_test_fix_prompt(check_result, test_content, source_content, project_path)

    try:
        agent = get_agent("coder")
        response = agent.generate(
            prompt=prompt,
            system="You are a test debugging expert. Analyze failures and provide minimal, correct fixes.",
            temperature=0.3,
            purpose="quality_gate_test_fix",
        )
        response_text = response.content.strip()
    except Exception as e:
        logger.error("llm_failed", error=str(e))
        return "failed"

    # Parse response
    fix_data = _parse_test_fix_response(response_text)

    if fix_data.get("fix_type") == "cannot_fix":
        reason = fix_data.get("reason", "Unknown")
        logger.info("cannot_fix_test", result_id=result_id, reason=reason)
        return "failed"

    # Get the file to fix
    file_to_fix = fix_data.get("file_to_fix")
    fixed_content = fix_data.get("fixed_content")

    if not file_to_fix or not fixed_content:
        logger.warning("incomplete_fix_response", result_id=result_id)
        return "failed"

    # Apply the fix
    target_file = project_path / file_to_fix
    try:
        target_file.write_text(fixed_content)
    except Exception as e:
        logger.error("apply_fix_failed", path=str(target_file), error=str(e))
        return "failed"

    # Verify the fix worked
    test_name = check_result.get("check_name")
    if _verify_test(project_path, test_name):
        qcr_store.mark_fixed(conn, result_id, fixed_by="claude-sonnet")
        logger.info(
            "test_fix_successful",
            result_id=result_id,
            fix_type=fix_data.get("fix_type"),
        )
        return "fixed"
    logger.info("test_fix_did_not_pass", result_id=result_id)
    # Check if we should escalate
    if current_attempts >= MAX_FIX_ATTEMPTS:
        # Create blocking task for manual review
        escalate_to_supervisor(conn, result_id)
        return "escalated"
    return "failed"


def fix_failing_tests(
    conn: psycopg.Connection[Any],
    project_id: str,
    limit: int = 5,
) -> dict[str, int]:
    """Fix all unfixed test failures for a project.

    Args:
        conn: Database connection
        project_id: Project ID
        limit: Maximum number of tests to attempt

    Returns:
        Dict with counts: fixed, failed, escalated
    """
    results = {"fixed": 0, "failed": 0, "escalated": 0}

    # Get unfixed pytest results
    unfixed = qcr_store.list_check_results(
        conn,
        project_id,
        check_type="pytest",
        unfixed_only=True,
        limit=limit,
    )

    for result in unfixed:
        outcome = fix_test_failure(conn, result["id"])
        results[outcome] += 1

    logger.info(
        "batch_test_fix_complete",
        project_id=project_id,
        **results,
    )

    return results
