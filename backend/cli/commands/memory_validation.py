"""Validation logic for memory system format standards."""

from __future__ import annotations

import re

import typer

from ..output import output_error

# FORMAT_STANDARD validation patterns
HEADER_PATTERNS = {
    "mandate": re.compile(r"^\*\*Mandate\*\*:"),
    "guardrail": re.compile(r"^\*\*Guardrail\*\*:"),
    "reference": re.compile(r"^\*\*Reference\*\*:"),
}
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
| 1 | Tier header | Must start with **Mandate**:, **Guardrail**:, or **Reference**: matching tier |
| 2 | Imperative mood | Commands not suggestions |
| 3 | Strong verb first | Lead with do / never / use / check / follow / avoid |
| 4 | One atomic rule | Single concept per episode |
| 5 | No custom delimiters | No ::, -> except in tables |
| 6 | No conversational | No please/remember/note:/you should |
| 7 | Terse content | Max 3 sentences, max 280 chars |
| 8 | Summary | 10-40 chars |

Example of GOOD format:
  **Mandate**: Use dt for all quality checks. Never run raw pytest or ruff. Why: hooks enforce dt path.

Example of BAD format:
  When working with git, you should remember to always commit first.
  Please don't use git stash because it might cause lost work.
"""

IMPERATIVE_PATTERNS = [
    re.compile(r"^\*\*(?:Mandate|Guardrail|Reference)\*\*:\s*(?:Use|Never|Always|Check|Follow|Avoid|Run|Keep|Prefer|Treat|Record|Verify|Fix|Delete|Remove|Commit|Push|Restart|Rebuild)\b"),
]


def validate_format_standard(content: str, summary: str, tier: str) -> list[str]:
    """Validate content against FORMAT_STANDARD. Returns list of errors."""
    errors: list[str] = []

    # Rule 1: Header format - must match tier
    header_pattern = HEADER_PATTERNS.get(tier)
    if header_pattern is None:
        errors.append(f"[1] header: Unsupported tier {tier}")
    elif not header_pattern.match(content):
        expected = {"mandate": "**Mandate**:", "guardrail": "**Guardrail**:", "reference": "**Reference**:"}[tier]
        errors.append(f"[1] header: Must start with {expected}")

    # Rule 2/3: Strong imperative opening
    if not any(pattern.match(content) for pattern in IMPERATIVE_PATTERNS):
        errors.append("[2] imperative: Start with direct instruction after header")

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

    # Rule 7: Keep content short and atomic
    sentence_count = sum(content.count(mark) for mark in ".!?")
    if sentence_count > 3 or len(content) > 280:
        errors.append(f"[7] terse: Too long ({sentence_count} sentences, {len(content)} chars)")

    # Rule 8: Summary length (10-40 chars)
    if len(summary) < 10:
        errors.append(f"[8] summary: Too short ({len(summary)} chars, need 10-40)")

    return errors


def validate_summary_length(summary: str) -> None:
    """Validate summary length and raise error if invalid."""
    if len(summary) > 40:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 40 chars.")
        raise typer.Exit(1)


def validate_content_format(content: str, summary: str, tier: str) -> None:
    """Validate content format and raise error if invalid."""
    format_errors = validate_format_standard(content, summary, tier)
    if format_errors:
        output_error("FORMAT_STANDARD violations detected:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
        raise typer.Exit(1)

    if content.count(".") > 3 or len(content) > 280:
        typer.echo("Hint: Long content detected. Consider splitting into separate episodes.", err=True)
