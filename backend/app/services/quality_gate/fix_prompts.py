"""Prompt building utilities for fix agent.

Constructs prompts for LLMs to fix lint/type errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.self_healing import StoredPattern
from .pattern_memory_utils import format_patterns_for_prompt


def _build_header_lines(
    check_type: str,
    file_path: str,
    line_number: int | None,
    check_name: str,
    error_message: str,
    file_content: str,
) -> list[str]:
    """Build the header section of the fix prompt."""
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
    return lines


_CHECK_TYPE_INSTRUCTIONS: dict[str, list[str]] = {
    "ruff": [
        "Fix the ruff linting error. Common fixes:",
        "- F401: Remove unused import",
        "- E501: Break long line (use parentheses or line continuation)",
        "- W291/W293: Remove trailing whitespace",
        "- E302/E303: Fix blank lines around functions/classes",
        "- F841: Remove unused variable or prefix with underscore",
        "",
    ],
    "types": [
        "Fix the type error. Common fixes:",
        "- Add type annotations",
        "- Add proper None checks",
        "- Use cast() or type guards",
        "- Fix return type annotations",
        "- Import types from typing module",
        "",
    ],
    "biome": [
        "Fix the Biome lint/format error. Common fixes:",
        "- Fix import order",
        "- Add missing semicolons",
        "- Fix unused variables",
        "- Apply consistent formatting",
        "",
    ],
    "tsc": [
        "Fix the TypeScript type error. Common fixes:",
        "- Add proper type annotations",
        "- Fix type mismatches",
        "- Handle undefined/null properly",
        "- Import missing types",
        "",
    ],
}


def _build_instructions_lines(check_type: str) -> list[str]:
    """Build check-type-specific instruction lines."""
    return _CHECK_TYPE_INSTRUCTIONS.get(check_type, [])


def _build_patterns_lines(similar_patterns: list[StoredPattern] | None) -> list[str]:
    """Build the similar patterns section if patterns are available."""
    if not similar_patterns:
        return []
    pattern_section = format_patterns_for_prompt(similar_patterns)
    if not pattern_section:
        return []
    return [pattern_section]


_RESPONSE_FORMAT_LINES = [
    "## Response Format",
    "",
    "Respond with ONLY the fixed file content, no explanation.",
    "If you cannot fix the error, respond with exactly: CANNOT_FIX: <reason>",
    "",
    "Do not include markdown code fences in your response.",
]


def build_fix_prompt(
    check_result: dict[str, Any],
    file_content: str,
    project_path: Path,
    similar_patterns: list[StoredPattern] | None = None,
) -> str:
    """Build prompt for fix agent.

    Args:
        check_result: Quality check result from DB
        file_content: Content of the file with the error
        project_path: Path to project root
        similar_patterns: Optional list of similar patterns to include

    Returns:
        Prompt string for the LLM
    """
    check_type = check_result["check_type"]
    error_message = check_result.get("error_message", "")
    file_path = check_result.get("file_path", "")
    line_number = check_result.get("line_number")
    check_name = check_result.get("check_name", "")

    lines = _build_header_lines(
        check_type, file_path, line_number, check_name, error_message, file_content
    )
    lines.extend(_build_instructions_lines(check_type))
    lines.extend(_build_patterns_lines(similar_patterns))
    lines.extend(_RESPONSE_FORMAT_LINES)

    return "\n".join(lines)
