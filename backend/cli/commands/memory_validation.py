"""Validation logic for memory system format standards."""

from __future__ import annotations

import re

import typer

from ..output import output_error

# FORMAT_STANDARD validation patterns
HEADER_PATTERN = re.compile(r"^\*\*[^*]+\*\*:")
CUSTOM_DELIMITER_PATTERN = re.compile(r"(?<![\|])\s*::\s*|(?<!\|)\s*->\s*(?!\|)")
CONVERSATIONAL_PATTERNS = [
    "please",
    "thank you",
    "you should",
    "i recommend",
    "remember",
    "make sure",
    "note:",
    "important:",
    "consider using",
    "feel free",
    "you might want",
    "it would be",
    "it's important to",
    "let me know",
    "i suggest",
]

FORMAT_STANDARD_HELP = """
FORMAT_STANDARD for memory episodes:

| # | Rule | Check |
|---|------|-------|
| 1 | Header format | Must start with **Topic**: |
| 2 | Imperative mood | Commands not suggestions |
| 3 | Articles dropped | Remove the/a/an where natural |
| 4 | One atomic rule | Single concept per episode |
| 5 | No custom delimiters | No ::, -> except in tables |
| 6 | No conversational | No please/remember/note:/you should |
| 7 | Terse content | Compress wordiness |
| 8 | Summary | 10-40 chars |

Example of GOOD format:
  **Git Safety**: Never git stash. Use /commit_it first. Lost work risk.

Example of BAD format:
  When working with git, you should remember to always commit first.
  Please don't use git stash because it might cause lost work.
"""


def validate_format_standard(content: str, summary: str) -> list[str]:
    """Validate content against FORMAT_STANDARD. Returns list of errors."""
    errors: list[str] = []

    # Rule 1: Header format - must start with **Topic**:
    if not HEADER_PATTERN.match(content):
        errors.append("[1] header: Must start with **Topic**: format")

    # Rule 5: No custom delimiters (:: or -> outside tables)
    # Allow | for tables, but catch standalone :: and ->
    lines = content.split("\n")
    for i, line in enumerate(lines):
        # Skip table rows (contain |)
        if "|" in line:
            continue
        if "::" in line or re.search(r"(?<!\|)\s*->\s*(?!\|)", line):
            errors.append(f"[5] delimiters: Line {i + 1} has :: or -> (use tables or rewrite)")
            break

    # Rule 6: No conversational patterns
    content_lower = content.lower()
    found_patterns = [p for p in CONVERSATIONAL_PATTERNS if p in content_lower]
    if found_patterns:
        errors.append(f"[6] conversational: Remove patterns: {', '.join(found_patterns[:3])}")

    # Rule 8: Summary length (10-40 chars)
    if len(summary) < 10:
        errors.append(f"[8] summary: Too short ({len(summary)} chars, need 10-40)")

    return errors


def validate_summary_length(summary: str) -> None:
    """Validate summary length and raise error if invalid."""
    if len(summary) > 40:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 40 chars.")
        raise typer.Exit(1)


def validate_content_format(content: str, summary: str) -> None:
    """Validate content format and raise error if invalid."""
    format_errors = validate_format_standard(content, summary)
    if format_errors:
        output_error("FORMAT_STANDARD violations detected:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
        raise typer.Exit(1)

    if content.count(".") > 3 or len(content) > 500:
        typer.echo("Hint: Long content detected. Consider splitting into separate episodes.", err=True)
