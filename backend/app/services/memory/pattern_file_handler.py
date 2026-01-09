"""Pattern file handling - File I/O for patterns in rules files.

Handles reading and writing patterns to/from markdown and JSON-lines formats.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def append_pattern_to_file(rules_path: Path, pattern: dict[str, Any]) -> None:
    """Append a formatted pattern to the rules file."""
    pattern_entry = format_pattern_for_rules(pattern)
    with open(rules_path, "a") as f:
        f.write("\n\n" + pattern_entry)


def remove_pattern_from_file(rules_path: Path, pattern_id: str | None) -> bool:
    """Remove a pattern from the rules file by its ID.

    Args:
        rules_path: Path to the rules file.
        pattern_id: The pattern ID to remove.

    Returns:
        True if pattern was found and removed.
    """
    if not pattern_id or not rules_path.exists():
        return False

    try:
        content = rules_path.read_text()

        pattern_marker = f"<!-- Pattern ID: {pattern_id}"

        if pattern_marker not in content:
            return False

        lines = content.split("\n")
        new_lines: list[str] = []
        skip_until_next_section = False
        found_pattern = False

        for line in lines:
            if pattern_marker in line:
                j = len(new_lines) - 1
                while j >= 0 and not new_lines[j].startswith("## "):
                    j -= 1
                if j >= 0:
                    new_lines = new_lines[:j]
                skip_until_next_section = True
                found_pattern = True
                continue

            if skip_until_next_section:
                if line.startswith("## "):
                    skip_until_next_section = False
                    new_lines.append(line)
                continue

            new_lines.append(line)

        if found_pattern:
            cleaned = "\n".join(new_lines).strip()
            rules_path.write_text(cleaned + "\n")
            logger.info(f"pattern_removed_from_file: id={pattern_id}")
            return True

    except Exception as e:
        logger.error(f"Failed to remove pattern from file: {e}")

    return False


def format_pattern_for_rules(pattern: dict[str, Any]) -> str:
    """Format a pattern as markdown for rules file."""
    lines = [
        f"## {pattern['title']}",
        "",
        pattern["content"],
    ]

    if pattern.get("rationale"):
        lines.extend(
            [
                "",
                f"*Rationale: {pattern['rationale']}*",
            ]
        )

    lines.extend(
        [
            "",
            f"<!-- Pattern ID: {pattern['id']} | Applied: {datetime.now().isoformat()} -->",
        ]
    )

    return "\n".join(lines)


def format_pattern_jsonl(pattern: dict[str, Any], include_content: bool = False) -> str:
    """Format a pattern as compact JSON-lines for progressive disclosure.

    Index format (for SessionStart, ~10 tokens per pattern):
    {"id":"abc","t":"title"}

    Full format (for expand, ~50 tokens per pattern):
    {"id":"abc","t":"title","c":"content","d":"domain","conf":0.85}

    Args:
        pattern: Pattern dict with id, title, content, pattern_type, confidence
        include_content: If True, include full content (for expand). Default False for index.

    Returns:
        Single JSON line (no trailing newline)
    """
    full_id = str(pattern.get("id", ""))
    short_id = full_id[-8:] if len(full_id) > 8 else full_id

    if include_content:
        compact = {
            "id": full_id,
            "t": pattern.get("title", ""),
            "c": pattern.get("content", ""),
            "d": pattern.get("pattern_type", "rule"),
            "conf": round(pattern.get("confidence", 0.5), 2),
        }
    else:
        compact = {
            "id": short_id,
            "t": pattern.get("title", ""),
        }

    return json.dumps(compact, separators=(",", ":"))


def parse_pattern_jsonl(line: str) -> dict[str, Any] | None:
    """Parse a JSON-lines pattern entry back to dict format.

    Handles both:
    - Index format: {"id":"short","t":"title"}
    - Full format: {"id":"full","t":"title","c":"content","d":"type","conf":0.85}

    Args:
        line: Single JSON line to parse

    Returns:
        Pattern dict with normalized keys, or None if parse fails
    """
    try:
        compact = json.loads(line.strip())
    except json.JSONDecodeError:
        return None

    return {
        "id": compact.get("id", ""),
        "title": compact.get("t", ""),
        "content": compact.get("c", ""),
        "pattern_type": compact.get("d", "rule"),
        "confidence": compact.get("conf", 0.5),
    }


def parse_patterns_file(content: str) -> list[dict[str, Any]]:
    """Parse a patterns file, detecting format automatically.

    Supports:
    - JSON-lines format (each line is a JSON object)
    - Legacy markdown format (## Title / content / <!-- Pattern ID -->)

    Args:
        content: Full file content

    Returns:
        List of pattern dicts
    """
    content = content.strip()
    if not content:
        return []

    first_line = content.split("\n")[0].strip()

    if first_line.startswith("{"):
        return _parse_jsonl_format(content)
    elif first_line.startswith("#"):
        return _parse_markdown_format(content)
    else:
        logger.warning(f"Unknown pattern file format: {first_line[:50]}")
        return []


def _parse_jsonl_format(content: str) -> list[dict[str, Any]]:
    """Parse JSON-lines format patterns."""
    patterns = []
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        parsed = parse_pattern_jsonl(line)
        if parsed:
            patterns.append(parsed)
    return patterns


def _parse_markdown_format(content: str) -> list[dict[str, Any]]:
    """Parse legacy markdown format patterns.

    Format:
    ## Title

    Content text here.

    *Rationale: ...*

    <!-- Pattern ID: uuid | Applied: timestamp -->
    """
    patterns = []

    sections = re.split(r"\n(?=## )", content)

    for section in sections:
        section = section.strip()
        if not section.startswith("## "):
            continue

        lines = section.split("\n")
        title = lines[0][3:].strip()

        pattern_id = ""
        id_match = re.search(r"<!-- Pattern ID: ([^\s|]+)", section)
        if id_match:
            pattern_id = id_match.group(1)

        content_lines = []
        rationale = ""
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("*Rationale:"):
                rationale = line[11:].rstrip("*").strip()
                continue
            if line.startswith("<!--"):
                continue
            if line:
                content_lines.append(line)

        patterns.append(
            {
                "id": pattern_id,
                "title": title,
                "content": "\n".join(content_lines),
                "rationale": rationale,
                "pattern_type": "rule",
                "confidence": 0.7,
            }
        )

    return patterns
