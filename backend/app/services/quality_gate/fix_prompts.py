"""Prompt building utilities for fix agent.

Constructs prompts for LLMs to fix lint/type errors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...services.self_healing import StoredPattern
from .pattern_memory_utils import format_patterns_for_prompt


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
    elif check_type == "types":
        lines.extend(
            [
                "Fix the type error. Common fixes:",
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

    # Add similar patterns if available
    if similar_patterns:
        pattern_section = format_patterns_for_prompt(similar_patterns)
        if pattern_section:
            lines.append(pattern_section)

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
