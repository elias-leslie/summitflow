"""Validation and formatting helpers for memory episode standards."""

from __future__ import annotations

import re

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
ACCEPTED_VERBS_DISPLAY = ", ".join(IMPERATIVE_VERBS)
IMPERATIVE_PATTERNS = [
    re.compile(
        rf"^\*\*[^*\n][^*\n]{{0,78}}\*\*:\s*(?:{'|'.join(IMPERATIVE_VERBS)})\b"
    ),
]

SAVE_EXAMPLE = """
Example:
  st memory save -s project --scope-id a-term -t guardrail -c 90 \\
    -S "Never bypass quality gates" \\
    "**Quality Gates**: Use st check for all checks. Never run raw pytest. Why: hooks enforce st path."

Limits:
  -S summary : 10-40 chars (hard)
  content    : per DB compactness policy (soft, warns)
               see Agent Hub /compactness for live thresholds
  content    : must start with **Topic**: then imperative verb
"""

FORMAT_EXAMPLE = """
Generate a valid body first:
  st memory format --topic "Quality Gates" \\
    --instruction "Use st check for all checks" \\
    --prohibition "Never run raw pytest" \\
    --why "hooks enforce st path"
"""

SAVE_QUICKSTART = f"""
Quickstart:
  st memory save -s project --scope-id a-term -t guardrail \\
    -S "Never bypass quality gates" \\
    "**Quality Gates**: Use st check for all checks. Never run raw pytest. Why: hooks enforce st path."

{FORMAT_EXAMPLE}
"""

FORMAT_STANDARD_HELP = f"""
{SAVE_QUICKSTART}

FORMAT_STANDARD for memory episodes:

| # | Rule | Check |
|---|------|-------|
| 1 | Topic header | Must start with **Topic**: where Topic is a compact specific subject, not a tier label |
| 2 | Imperative mood | Commands not suggestions |
| 3 | Strong verb first | Lead with one of: {ACCEPTED_VERBS_DISPLAY} |
| 4 | One atomic rule | Single concept per episode |
| 5 | No custom delimiters | No ::, -> except in tables |
| 6 | No conversational | No please/remember/note:/you should |
| 7 | Terse content | Per DB compactness policy (see /api/compactness/policy) |
| 8 | Summary | 10-40 chars |

Example of GOOD format:
  **Quality Checks**: Use st check for all quality checks. Never run raw pytest or ruff. Why: hooks enforce st path.

Example of BAD format:
  **Mandate**: Use st check for all quality checks.
  When working with git, you should remember to always commit first.
  Please don't use git stash because it might cause lost work.
""" + SAVE_EXAMPLE

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


def validate_format_standard(content: str, summary: str, tier: str) -> tuple[list[str], list[str]]:
    """Validate content against FORMAT_STANDARD. Returns blocking errors."""
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
        errors.append(
            "[2] imperative: Start with a strong verb right after the header. "
            f"Accepted verbs: {ACCEPTED_VERBS_DISPLAY}"
        )

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
    format_errors, _hints = validate_format_standard(content, summary, tier)
    if format_errors:
        output_error("FORMAT_STANDARD violations detected:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
        raise typer.Exit(1)


def validate_memory_authoring(
    label: str, content: str, summary: str, tier: str, *, bypass_compactness: bool = False
) -> None:
    """Run the Caveman and FORMAT_STANDARD gates together, reporting all violations in one pass."""
    from .compactness import analyze_compactness

    validate_episode_content_present(content)
    compact_errors: list[str] = []
    if not bypass_compactness:
        compact_errors = list(analyze_compactness(content, kind="memory").errors)
    format_errors, _hints = validate_format_standard(content, summary, tier)
    if not compact_errors and not format_errors:
        return
    if compact_errors:
        output_error(f"memory {label}: strict Caveman gate failed")
        for error in compact_errors:
            output_error(f"  - {error}")
    if format_errors:
        output_error("FORMAT_STANDARD violations detected:")
        for err in format_errors:
            typer.echo(f"  {err}", err=True)
        typer.echo(FORMAT_STANDARD_HELP, err=True)
    raise typer.Exit(1)
