"""Validation and formatting helpers for memory episode standards."""

from __future__ import annotations

import re
from collections.abc import Iterable

import typer

from ..output import output_error

# FORMAT_STANDARD validation patterns
TOPIC_HEADER_PATTERN = re.compile(r"^\*\*[^*\n][^*\n]{0,78}\*\*:")
CUSTOM_DELIMITER_PATTERN = re.compile(r"(?<![\|])\s*::\s*|(?<!\|)\s*->\s*(?!\|)")
LIST_PATTERN = re.compile(r"(?m)^\s*(?:[-*]|\d+\.)\s+")
MULTI_HEADER_PATTERN = re.compile(r"(?m)^\*\*[^*\n][^*\n]{0,78}\*\*:")
HEADER_EXTRACT_PATTERN = re.compile(r"^\*\*(?P<topic>[^*\n][^*\n]{0,78})\*\*:")
RESERVED_TIER_HEADERS = {"Mandate", "Guardrail", "Reference"}
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

SAVE_EXAMPLE = """
Example:
  st memory save -s project --scope-id terminal -t guardrail -c 90 \\
    -S "Never bypass quality gates" \\
    "**Quality Gates**: Use dt for all checks. Never run raw pytest. Why: hooks enforce dt path."

Limits:
  -S summary : 10-40 chars (hard)
  content    : <=3 sentences / <=280 chars (soft, warns)
  content    : must start with **Topic**: then imperative verb
"""

FORMAT_EXAMPLE = """
Generate a valid body first:
  st memory format --topic "Quality Gates" \\
    --instruction "Use dt for all checks" \\
    --prohibition "Never run raw pytest" \\
    --why "hooks enforce dt path"
"""

SAVE_QUICKSTART = f"""
Quickstart:
  st memory save -s project --scope-id terminal -t guardrail \\
    -S "Never bypass quality gates" \\
    "**Quality Gates**: Use dt for all checks. Never run raw pytest. Why: hooks enforce dt path."

{FORMAT_EXAMPLE}
"""

FORMAT_STANDARD_HELP = f"""
{SAVE_QUICKSTART}

FORMAT_STANDARD for memory episodes:

| # | Rule | Check |
|---|------|-------|
| 1 | Topic header | Must start with **Topic**: where Topic is a compact specific subject, not a tier label |
| 2 | Imperative mood | Commands not suggestions |
| 3 | Strong verb first | Lead with do / never / use / check / follow / avoid |
| 4 | One atomic rule | Single concept per episode |
| 5 | No custom delimiters | No ::, -> except in tables |
| 6 | No conversational | No please/remember/note:/you should |
| 7 | Terse content | Prefer 3 sentences max, prefer 280 chars max |
| 8 | Summary | 10-40 chars |

Example of GOOD format:
  **Quality Checks**: Use dt for all quality checks. Never run raw pytest or ruff. Why: hooks enforce dt path.

Example of BAD format:
  **Mandate**: Use dt for all quality checks.
  When working with git, you should remember to always commit first.
  Please don't use git stash because it might cause lost work.
""" + SAVE_EXAMPLE

IMPERATIVE_VERBS = (
    "Use",
    "Never",
    "Always",
    "Check",
    "Follow",
    "Avoid",
    "Run",
    "Keep",
    "Prefer",
    "Treat",
    "Record",
    "Verify",
    "Fix",
    "Delete",
    "Remove",
    "Commit",
    "Push",
    "Restart",
    "Rebuild",
)
IMPERATIVE_PATTERNS = [
    re.compile(
        rf"^\*\*[^*\n][^*\n]{{0,78}}\*\*:\s*(?:{'|'.join(IMPERATIVE_VERBS)})\b"
    ),
]


def _normalize_sentence(text: str) -> str:
    """Trim and ensure sentence-ending punctuation."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        return f"{cleaned}."
    return cleaned


def _normalize_topic(topic: str) -> str:
    """Collapse internal whitespace and reject invalid topic text."""
    cleaned = re.sub(r"\s+", " ", topic.strip())
    if not cleaned:
        raise typer.BadParameter("Topic is required")
    if "**" in cleaned or ":" in cleaned or "\n" in cleaned:
        raise typer.BadParameter("Topic must be plain text without bold markers, colons, or newlines")
    if len(cleaned) > 79:
        raise typer.BadParameter("Topic must be 79 characters or fewer")
    return cleaned


def validate_episode_content_present(content: str) -> str:
    """Require non-empty episode content and return the original string."""
    if not content.strip():
        output_error("Content is required and cannot be blank.")
        raise typer.Exit(1)
    return content


def emit_save_quickstart_error(
    *,
    missing_summary: bool = False,
    missing_content: bool = False,
    blank_content: bool = False,
) -> None:
    """Print a self-contained `st memory save` quickstart error and exit."""
    problems: list[str] = []
    if missing_summary:
        problems.append("--summary")
    if missing_content:
        problems.append("content or --content-file")

    if blank_content and not missing_content:
        message = "st memory save content cannot be blank."
    elif problems:
        joined = " and ".join(problems)
        message = f"st memory save requires {joined}."
    else:
        message = "st memory save input is invalid."

    output_error(message)
    typer.echo(SAVE_QUICKSTART, err=True)
    raise typer.Exit(1)


def build_episode_content(
    topic: str,
    instruction: str,
    prohibition: str | None = None,
    why: str | None = None,
) -> str:
    """Build a standard memory episode body from structured parts."""
    cleaned_topic = _normalize_topic(topic)
    parts = [_normalize_sentence(instruction)]
    if prohibition:
        parts.append(_normalize_sentence(prohibition))
    if why:
        parts.append(_normalize_sentence(f"Why: {why}"))

    body = " ".join(part for part in parts if part)
    return f"**{cleaned_topic}**: {body}"


def suggest_summary(instruction: str, limit: int = 40) -> str:
    """Suggest a compact summary from the primary instruction."""
    summary = instruction.strip()
    if not summary:
        return ""

    summary = re.sub(rf"^(?:{'|'.join(IMPERATIVE_VERBS)})\s+", "", summary, flags=re.IGNORECASE)
    summary = summary.rstrip(".!? ")
    if len(summary) <= limit:
        return summary

    clipped = summary[:limit].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(".!? ")


def format_guidance_hints(content: str, summary: str) -> list[str]:
    """Return soft guidance hints that should not block saving."""
    hints: list[str] = []
    header_match = HEADER_EXTRACT_PATTERN.match(content)
    if header_match and len(header_match.group("topic")) > 35:
        hints.append("Topic header is long; prefer 35 chars or fewer when possible.")
    sentence_count = len(re.findall(r"[.!?](?:\s|$)", content))
    if sentence_count > 3:
        hints.append(f"Content is {sentence_count} sentences; prefer 3 or fewer when possible.")
    if len(content) > 280:
        hints.append(f"Content is {len(content)} chars; prefer 280 or fewer when possible.")
    if len(summary) > 35:
        hints.append(f"Summary is {len(summary)} chars; prefer 35 or fewer when possible.")
    return hints


def emit_format_guidance_hints(hints: Iterable[str]) -> None:
    """Print non-blocking FORMAT_STANDARD hints."""
    for hint in hints:
        typer.echo(f"Hint: {hint}", err=True)


def validate_format_standard(content: str, summary: str, tier: str) -> tuple[list[str], list[str]]:
    """Validate content against FORMAT_STANDARD. Returns blocking errors and soft hints."""
    errors: list[str] = []
    hints: list[str] = []
    header_match = HEADER_EXTRACT_PATTERN.match(content)

    # Rule 1: Header format - must be a bold topic, tier is separate metadata
    if tier not in {"mandate", "guardrail", "reference"}:
        errors.append(f"[1] header: Unsupported tier {tier}")
    elif not TOPIC_HEADER_PATTERN.match(content):
        errors.append("[1] header: Must start with a bold topic header like **Git Safety**:")
    elif header_match and header_match.group("topic").strip() in RESERVED_TIER_HEADERS:
        errors.append("[1] header: Use a specific topic header, not **Mandate**/**Guardrail**/**Reference**")

    # Rule 2/3: Strong imperative opening
    if not any(pattern.match(content) for pattern in IMPERATIVE_PATTERNS):
        errors.append("[2] imperative: Start with direct instruction after header")

    # Rule 4: One atomic rule - reject list-shaped multi-rule content
    if LIST_PATTERN.search(content):
        errors.append("[4] atomic: Use one compact rule, not a bullet or numbered list")
    if len(MULTI_HEADER_PATTERN.findall(content)) > 1:
        errors.append("[4] atomic: Use a single episode header")

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

    hints.extend(format_guidance_hints(content, summary))
    return errors, hints


def validate_summary_length(summary: str) -> None:
    """Validate summary length and raise error if invalid."""
    if len(summary) > 40:
        output_error(f"Summary too long ({len(summary)} chars). Keep it under 40 chars.")
        typer.echo(SAVE_QUICKSTART, err=True)
        raise typer.Exit(1)


def validate_content_format(content: str, summary: str, tier: str) -> None:
    """Validate content format and raise error if invalid."""
    validate_episode_content_present(content)
    format_errors, hints = validate_format_standard(content, summary, tier)
    if format_errors:
        output_error("FORMAT_STANDARD violations detected:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
        raise typer.Exit(1)
    emit_format_guidance_hints(hints)
