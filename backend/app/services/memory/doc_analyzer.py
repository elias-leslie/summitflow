"""Document analysis for the memory health checker.

Handles parsing, conflict detection, sync suggestions, and version tracking
for CLAUDE.md, AGENTS.md, and rules files.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

from ...storage import memory as memory_storage
from ...storage.connection import get_connection
from .types import get_project_root

logger = logging.getLogger(__name__)


def parse_claude_md(project_id: str) -> list[dict[str, Any]]:
    """Parse CLAUDE.md into structured sections.

    Extracts ## headers and their content from CLAUDE.md and AGENTS.md
    to enable conflict detection and sync suggestions.

    Args:
        project_id: Project to parse

    Returns:
        List of section dicts with:
            - doc_file: 'CLAUDE.md' or 'AGENTS.md'
            - section_title: the ## header text
            - content: text content under that header
            - line_start: line number where section starts
            - line_end: line number where section ends
    """
    sections: list[dict[str, Any]] = []

    # Get project root path
    project_root = get_project_root(project_id)
    if not project_root:
        return []

    # Parse both CLAUDE.md and AGENTS.md
    doc_files = ["CLAUDE.md", "AGENTS.md"]

    for doc_file in doc_files:
        doc_path = project_root / doc_file
        if not doc_path.exists():
            continue

        try:
            content = doc_path.read_text(encoding="utf-8")
            lines = content.split("\n")

            # Pattern to match ## headers (level 2)
            header_pattern = re.compile(r"^##\s+(.+)$")

            current_section: dict[str, Any] | None = None
            section_content_lines: list[str] = []

            for i, line in enumerate(lines, start=1):
                header_match = header_pattern.match(line)

                if header_match:
                    # Save previous section if exists
                    if current_section:
                        current_section["content"] = "\n".join(section_content_lines).strip()
                        current_section["line_end"] = i - 1
                        sections.append(current_section)

                    # Start new section
                    current_section = {
                        "doc_file": doc_file,
                        "section_title": header_match.group(1).strip(),
                        "content": "",
                        "line_start": i,
                        "line_end": i,
                    }
                    section_content_lines = []
                elif current_section:
                    section_content_lines.append(line)

            # Don't forget the last section
            if current_section:
                current_section["content"] = "\n".join(section_content_lines).strip()
                current_section["line_end"] = len(lines)
                sections.append(current_section)

        except Exception as e:
            logger.warning(f"Failed to parse {doc_file}: {e}")
            continue

    return sections


def parse_doc_sections(doc_path: Path, doc_file: str) -> list[dict[str, Any]]:
    """Parse a markdown document into sections.

    Args:
        doc_path: Path to the markdown file
        doc_file: Name for the doc_file field

    Returns:
        List of section dicts with doc_file, section_title, content, line_start, line_end
    """
    sections: list[dict[str, Any]] = []

    try:
        content = doc_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        header_pattern = re.compile(r"^##\s+(.+)$")
        current_section: dict[str, Any] | None = None
        section_content_lines: list[str] = []

        for i, line in enumerate(lines, start=1):
            header_match = header_pattern.match(line)

            if header_match:
                if current_section:
                    current_section["content"] = "\n".join(section_content_lines).strip()
                    current_section["line_end"] = i - 1
                    sections.append(current_section)

                current_section = {
                    "doc_file": doc_file,
                    "section_title": header_match.group(1).strip(),
                    "content": "",
                    "line_start": i,
                    "line_end": i,
                }
                section_content_lines = []
            elif current_section:
                section_content_lines.append(line)

        if current_section:
            current_section["content"] = "\n".join(section_content_lines).strip()
            current_section["line_end"] = len(lines)
            sections.append(current_section)

    except Exception as e:
        logger.warning(f"Failed to parse {doc_file}: {e}")

    return sections


def is_similar_content(text1: str, text2: str, threshold: float = 0.6) -> bool:
    """Check if two texts are semantically similar using word overlap.

    Simple heuristic based on significant word overlap.

    Args:
        text1: First text to compare
        text2: Second text to compare
        threshold: Jaccard similarity threshold (0.0-1.0)

    Returns:
        True if similarity exceeds threshold
    """

    # Extract significant words (length > 3)
    def get_words(text: str) -> set[str]:
        words = set()
        for word in text.split():
            # Remove punctuation
            word = word.strip(".,;:!?()[]{}\"'")
            if len(word) > 3 and word.isalpha():
                words.add(word.lower())
        return words

    words1 = get_words(text1)
    words2 = get_words(text2)

    if not words1 or not words2:
        return False

    # Jaccard similarity
    intersection = len(words1 & words2)
    union = len(words1 | words2)

    return (intersection / union) >= threshold if union > 0 else False


def check_for_contradictions(
    doc_content: str, pattern_content: str, doc_title: str, pattern_title: str
) -> str | None:
    """Check if doc section and pattern have contradicting guidance.

    Looks for patterns like:
    - Doc says 'use X' but pattern says 'avoid X' or 'use Y instead of X'
    - Doc says 'never X' but pattern says 'always X'
    - Doc says 'prefer X' but pattern says 'prefer Y' on same topic

    Args:
        doc_content: Lowercase doc section content
        pattern_content: Lowercase pattern content
        doc_title: Lowercase doc section title
        pattern_title: Lowercase pattern title

    Returns:
        Explanation string if contradiction found, None otherwise
    """
    # Check for same topic (title similarity)
    if not is_similar_content(doc_title, pattern_title, threshold=0.3):
        return None

    # Opposing keyword pairs
    opposites = [
        ("always", "never"),
        ("use", "avoid"),
        ("prefer", "avoid"),
        ("required", "optional"),
        ("must", "should not"),
        ("recommended", "deprecated"),
        ("enable", "disable"),
    ]

    for word1, word2 in opposites:
        # Check if doc has word1 and pattern has word2, or vice versa
        if (word1 in doc_content and word2 in pattern_content) or (
            word2 in doc_content and word1 in pattern_content
        ):
            return (
                f"Potential conflict: doc uses '{word1}'/'{word2}' guidance "
                f"that may contradict pattern guidance"
            )

    return None


def detect_doc_conflicts(project_id: str) -> list[dict[str, Any]]:
    """Detect conflicts between CLAUDE.md/AGENTS.md sections and learned patterns.

    Compares doc sections to patterns and flags contradictions where:
    - A pattern recommends 'use X' but doc says 'use Y'
    - A pattern deprecates something still in the docs
    - Doc and pattern give conflicting instructions on same topic

    Uses semantic similarity via embedding comparison.

    Args:
        project_id: Project to analyze

    Returns:
        List of conflict dicts with:
            - conflict_type: 'contradicting_guidance' | 'stale_reference' | 'duplicate_content'
            - doc_section: {doc_file, section_title, line_start, content_excerpt}
            - pattern: {id, title, content_excerpt}
            - explanation: why this is a conflict
            - severity: 'high' | 'medium' | 'low'
    """
    conflicts: list[dict[str, Any]] = []

    # Get doc sections
    sections = parse_claude_md(project_id)
    if not sections:
        return []

    # Get applied patterns for this project
    patterns = memory_storage.list_patterns(
        project_id=project_id,
        status="applied",
        limit=200,
    )

    if not patterns:
        return []

    # Compare each section against patterns for potential conflicts
    for section in sections:
        section_lower = section["content"].lower()
        section_title_lower = section["section_title"].lower()

        for pattern in patterns:
            pattern_content = pattern.get("content", "").lower()
            pattern_title = pattern.get("title", "").lower()

            # Skip empty content
            if not pattern_content or not section_lower:
                continue

            # Check for duplicate content (high similarity)
            if is_similar_content(section_lower, pattern_content, threshold=0.6):
                conflicts.append(
                    {
                        "conflict_type": "duplicate_content",
                        "doc_section": {
                            "doc_file": section["doc_file"],
                            "section_title": section["section_title"],
                            "line_start": section["line_start"],
                            "content_excerpt": section["content"][:200],
                        },
                        "pattern": {
                            "id": pattern.get("id"),
                            "title": pattern.get("title"),
                            "content_excerpt": pattern.get("content", "")[:200],
                        },
                        "explanation": f"Pattern '{pattern.get('title')}' has similar content to "
                        f"section '{section['section_title']}' in {section['doc_file']}. "
                        "Consider consolidating.",
                        "severity": "low",
                    }
                )
                continue

            # Check for contradicting guidance
            # Look for opposing keywords
            contradictions = check_for_contradictions(
                section_lower, pattern_content, section_title_lower, pattern_title
            )

            if contradictions:
                conflicts.append(
                    {
                        "conflict_type": "contradicting_guidance",
                        "doc_section": {
                            "doc_file": section["doc_file"],
                            "section_title": section["section_title"],
                            "line_start": section["line_start"],
                            "content_excerpt": section["content"][:200],
                        },
                        "pattern": {
                            "id": pattern.get("id"),
                            "title": pattern.get("title"),
                            "content_excerpt": pattern.get("content", "")[:200],
                        },
                        "explanation": contradictions,
                        "severity": "high"
                        if "must" in section_lower or "never" in section_lower
                        else "medium",
                    }
                )

    return conflicts


def generate_sync_suggestions(project_id: str) -> list[dict[str, Any]]:
    """Generate suggestions for synchronizing patterns with CLAUDE.md.

    Suggests:
    - pattern_should_be_in_claude_md: High-confidence patterns not in docs
    - doc_section_could_be_pattern: Doc sections that could become patterns
    - pattern_duplicates_doc: Pattern content already in docs

    Args:
        project_id: Project to analyze

    Returns:
        List of suggestion dicts with:
            - suggestion_type: Type of suggestion
            - pattern_id: Pattern ID (if applicable)
            - pattern_title: Pattern title (if applicable)
            - doc_file: Doc file (if applicable)
            - section_title: Doc section title (if applicable)
            - suggestion: Human-readable suggestion text
            - action: Recommended action ('add_to_claude_md', 'create_pattern', 'consolidate')
    """
    suggestions: list[dict[str, Any]] = []

    # Get doc sections
    sections = parse_claude_md(project_id)

    # Get high-confidence applied patterns
    patterns = memory_storage.list_patterns(
        project_id=project_id,
        status="applied",
        limit=200,
    )

    # Suggestion 1: High-confidence patterns not covered by CLAUDE.md
    section_content_combined = " ".join(s["content"].lower() for s in sections).lower()

    for pattern in patterns:
        confidence = pattern.get("confidence", 0)
        pattern_title = pattern.get("title", "")
        pattern_content = pattern.get("content", "")

        # Skip low confidence patterns
        if confidence < 0.85:
            continue

        # Check if pattern content is already covered in docs
        if not is_similar_content(pattern_content.lower(), section_content_combined, threshold=0.4):
            # High-confidence pattern not in docs
            suggestions.append(
                {
                    "suggestion_type": "pattern_should_be_in_claude_md",
                    "pattern_id": pattern.get("id"),
                    "pattern_title": pattern_title,
                    "doc_file": None,
                    "section_title": None,
                    "suggestion": f"Pattern '{pattern_title}' (confidence: {confidence:.0%}) "
                    "has proven useful and should be added to CLAUDE.md for visibility.",
                    "action": "add_to_claude_md",
                }
            )

    # Suggestion 2: Doc sections that look like they could be learned patterns
    # (imperative guidance not tracked as patterns)
    guidance_keywords = ["must", "always", "never", "required", "mandatory", "forbidden"]

    for section in sections:
        section_content_lower = section["content"].lower()

        # Check if section has strong guidance
        has_guidance = any(kw in section_content_lower for kw in guidance_keywords)

        if has_guidance and len(section["content"]) < 500:  # Concise enough for pattern
            # Check if there's already a matching pattern
            matching_pattern = None
            for pattern in patterns:
                if is_similar_content(
                    section["content"].lower(),
                    pattern.get("content", "").lower(),
                    threshold=0.5,
                ):
                    matching_pattern = pattern
                    break

            if not matching_pattern:
                suggestions.append(
                    {
                        "suggestion_type": "doc_section_could_be_pattern",
                        "pattern_id": None,
                        "pattern_title": None,
                        "doc_file": section["doc_file"],
                        "section_title": section["section_title"],
                        "suggestion": f"Section '{section['section_title']}' in {section['doc_file']} "
                        "contains guidance that could be tracked as a learned pattern "
                        "for adherence monitoring.",
                        "action": "create_pattern",
                    }
                )

    return suggestions


def track_doc_versions(project_id: str) -> list[dict[str, Any]]:
    """Track document versions by storing content hashes as observations.

    Stores CLAUDE.md and AGENTS.md content hashes to enable:
    - Detecting when docs have changed
    - Querying version history
    - Triggering sync suggestions on changes

    Args:
        project_id: Project to track

    Returns:
        List of tracked doc dicts with:
            - doc_file: filename
            - content_hash: SHA-256 hash
            - is_new_version: whether this is a new hash
    """
    tracked: list[dict[str, Any]] = []

    # Get project root path
    project_root = get_project_root(project_id)
    if not project_root:
        return []

    doc_files = ["CLAUDE.md", "AGENTS.md"]

    for doc_file in doc_files:
        doc_path = project_root / doc_file
        if not doc_path.exists():
            continue

        try:
            content = doc_path.read_text(encoding="utf-8")
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            # Check if we already have this version tracked
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT narrative FROM observations
                    WHERE project_id = %s
                      AND observation_type = 'doc_version'
                      AND title = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (project_id, doc_file),
                )
                row = cur.fetchone()
                existing_hash = row[0] if row else None

            is_new_version = existing_hash != content_hash

            if is_new_version:
                # Store new version observation
                memory_storage.create_observation(
                    project_id=project_id,
                    session_id="health-check",
                    agent_type="health-checker",
                    observation_type="doc_version",
                    title=doc_file,
                    narrative=content_hash,
                    priority="low",
                    confidence=1.0,
                    facts={"content_length": len(content), "previous_hash": existing_hash},
                )
                logger.info(f"Tracked new doc version: {doc_file} -> {content_hash}")

            tracked.append(
                {
                    "doc_file": doc_file,
                    "content_hash": content_hash,
                    "is_new_version": is_new_version,
                }
            )

        except Exception as e:
            logger.warning(f"Failed to track version for {doc_file}: {e}")
            continue

    return tracked
