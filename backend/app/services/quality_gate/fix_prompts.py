"""Prompt building utilities for fix agent.

Constructs prompts for LLMs to fix lint/type errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.self_healing.pattern_memory import StoredPattern
from .pattern_memory_utils import format_patterns_for_prompt


def build_fix_prompt(
    check_result: dict[str, Any],
    file_content: str,
    project_path: Path,
    similar_patterns: list[StoredPattern] | None = None,
    is_supervisor: bool = False,
) -> str:
    """Build prompt for fix agent."""
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

    instructions = {
        "ruff": "Fix the ruff linting error (F401, E501, W291/293, E302/303, F841).",
        "mypy": "Fix the mypy type error (Add annotations, None checks, cast/guards).",
        "biome": "Fix the Biome lint/format error (Import order, semicolons, variables).",
        "tsc": "Fix the TypeScript type error (Add annotations, fix mismatches, handle undefined).",
    }
    lines.append(instructions.get(check_type, "Fix the error."))

    if similar_patterns and (pattern_section := format_patterns_for_prompt(similar_patterns)):
        lines.append(f"\n{pattern_section}")

    lines.extend(
        [
            "",
            "## Response Format",
            "",
            "Respond with ONLY the fixed file content, no explanation.",
            "If you cannot fix the error, respond with exactly: CANNOT_FIX: <reason>",
            "",
            "Do not include markdown code fences in your response.",
        ]
    )

    prompt = "\n".join(lines)
    if is_supervisor:
        return f"""Previous fix attempts have failed. Try a different approach.

{prompt}

IMPORTANT: Previous attempts failed. Consider:
- Reading surrounding context more carefully
- The error might require structural changes, not just line fixes
- Check if imports or dependencies are missing
- Verify the fix actually addresses the root cause
"""
    return prompt
