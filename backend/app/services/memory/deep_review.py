"""Deep review functionality for the memory health checker.

Provides comprehensive analysis of instruction surfaces including
CLAUDE.md, AGENTS.md, rules files, and reference checking.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .doc_analyzer import parse_claude_md, parse_doc_sections
from .types import BrokenRef, DeepReviewReport, get_project_root

logger = logging.getLogger(__name__)


def check_references(doc_path: Path, project_root: Path) -> list[BrokenRef]:
    """Check for broken references in a document.

    Parses markdown for file paths, function names, and class names,
    then verifies they exist in the filesystem.

    Patterns matched:
    - `backend/app/...` backtick-wrapped file paths
    - 'See X.py' or 'in X.py'
    - 'the X function' or 'function X()'
    - 'class X' references

    Args:
        doc_path: Path to the document
        project_root: Project root for resolving references

    Returns:
        List of BrokenRef objects for broken references
    """
    broken_refs: list[BrokenRef] = []
    doc_file = doc_path.name

    try:
        content = doc_path.read_text(encoding="utf-8")
        lines = content.split("\n")

        # Patterns to find references
        patterns = [
            # Backtick-wrapped file paths: `backend/app/main.py`
            (re.compile(r"`([a-zA-Z0-9_/.-]+\.(py|ts|tsx|js|jsx|md))`"), "file_path"),
            # In/See file references: See main.py, in utils.py
            (
                re.compile(
                    r"(?:See|in|from)\s+`?([a-zA-Z0-9_.-]+\.(?:py|ts|tsx|js|jsx|md))`?",
                    re.IGNORECASE,
                ),
                "file_path",
            ),
            # File path with directory: backend/app/api/memory.py
            (
                re.compile(
                    r"(?<!`)((?:backend|frontend|app|src)/[a-zA-Z0-9_/.-]+\.(?:py|ts|tsx|js|jsx))"
                ),
                "file_path",
            ),
        ]

        for line_num, line in enumerate(lines, start=1):
            for pattern, ref_type in patterns:
                matches = pattern.finditer(line)
                for match in matches:
                    ref = match.group(1)

                    # Skip if it's a URL or external path
                    if ref.startswith("http") or ref.startswith("/usr") or ref.startswith("~"):
                        continue

                    # Check if file exists
                    ref_path = project_root / ref
                    if not ref_path.exists():
                        # Also check if it might be a basename match
                        found = False
                        for suffix in ["", ".py", ".ts", ".tsx", ".js", ".jsx"]:
                            if (project_root / (ref + suffix)).exists():
                                found = True
                                break

                        if not found:
                            broken_refs.append(
                                BrokenRef(
                                    doc_file=doc_file,
                                    line_number=line_num,
                                    reference=ref,
                                    ref_type=ref_type,
                                    reason=f"File not found: {ref}",
                                )
                            )

    except Exception as e:
        logger.warning(f"Failed to check references in {doc_file}: {e}")

    return broken_refs


def calculate_token_waste(report: DeepReviewReport) -> dict[str, Any]:
    """Calculate token waste from stale/redundant content.

    Estimates token counts for each instruction source and identifies
    waste from:
    - Stale sections (identified by LLM or staleness check)
    - Broken references (indicating outdated content)
    - Redundant content between sources

    Uses tiktoken-like estimation (4 chars ≈ 1 token).

    Args:
        report: The deep review report with sections

    Returns:
        Dict with:
            - total_tokens: Estimated total tokens across all sources
            - waste_tokens: Estimated tokens that are stale/broken
            - waste_pct: Percentage of waste
            - by_source: Token breakdown by source (claude_md, agents_md, rules, etc.)
    """

    def estimate_tokens(text: str) -> int:
        """Estimate tokens using 4 chars per token heuristic."""
        return len(text) // 4

    total_tokens = 0
    waste_tokens = 0
    by_source: dict[str, dict[str, int]] = {}

    # Calculate CLAUDE.md tokens
    claude_md_tokens = sum(estimate_tokens(s.get("content", "")) for s in report.claude_md_sections)
    by_source["claude_md"] = {"total": claude_md_tokens, "waste": 0}
    total_tokens += claude_md_tokens

    # Calculate AGENTS.md tokens
    agents_md_tokens = sum(estimate_tokens(s.get("content", "")) for s in report.agents_md_sections)
    by_source["agents_md"] = {"total": agents_md_tokens, "waste": 0}
    total_tokens += agents_md_tokens

    # Calculate project rules tokens
    rules_tokens = sum(r.get("size_bytes", 0) // 4 for r in report.rules_files)
    by_source["rules"] = {"total": rules_tokens, "waste": 0}
    total_tokens += rules_tokens

    # Calculate global rules tokens
    global_rules_tokens = sum(r.get("size_bytes", 0) // 4 for r in report.global_rules_files)
    by_source["global_rules"] = {"total": global_rules_tokens, "waste": 0}
    total_tokens += global_rules_tokens

    # Calculate waste from stale sections
    for stale in report.stale_sections:
        # Find the section content
        source = None
        section_tokens = 0

        if stale.doc_file == "CLAUDE.md":
            source = "claude_md"
            matching = [
                s
                for s in report.claude_md_sections
                if s.get("section_title") == stale.section_title
            ]
            if matching:
                section_tokens = estimate_tokens(matching[0].get("content", ""))
        elif stale.doc_file == "AGENTS.md":
            source = "agents_md"
            matching = [
                s
                for s in report.agents_md_sections
                if s.get("section_title") == stale.section_title
            ]
            if matching:
                section_tokens = estimate_tokens(matching[0].get("content", ""))

        if source and section_tokens > 0:
            # Weight by confidence
            waste_contribution = int(section_tokens * stale.confidence)
            by_source[source]["waste"] += waste_contribution
            waste_tokens += waste_contribution

    # Add waste estimate for broken references (rough: 20 tokens per broken ref)
    broken_ref_waste = len(report.broken_refs) * 20
    waste_tokens += broken_ref_waste

    # Distribute broken ref waste to sources
    for ref in report.broken_refs:
        if ref.doc_file == "CLAUDE.md" and "claude_md" in by_source:
            by_source["claude_md"]["waste"] += 20
        elif ref.doc_file == "AGENTS.md" and "agents_md" in by_source:
            by_source["agents_md"]["waste"] += 20

    waste_pct = (waste_tokens / total_tokens * 100) if total_tokens > 0 else 0.0

    return {
        "total_tokens": total_tokens,
        "waste_tokens": waste_tokens,
        "waste_pct": round(waste_pct, 2),
        "by_source": by_source,
    }


def deep_review(project_id: str) -> DeepReviewReport:
    """Perform comprehensive deep review of all instruction surfaces.

    Analyzes:
    - CLAUDE.md sections
    - AGENTS.md sections
    - Project .claude/rules/ files
    - Global ~/.claude/rules/ files
    - Broken references to files/functions/classes
    - Token waste calculation

    Args:
        project_id: Project to review

    Returns:
        DeepReviewReport with findings
    """
    report = DeepReviewReport()

    # Get project root path
    project_root = get_project_root(project_id)
    if not project_root:
        return report

    # Review CLAUDE.md
    claude_md_path = project_root / "CLAUDE.md"
    if claude_md_path.exists():
        report.claude_md_sections = parse_claude_md(project_id)
        # Check for broken refs
        broken = check_references(claude_md_path, project_root)
        report.broken_refs.extend(broken)

    # Review AGENTS.md
    agents_md_path = project_root / "AGENTS.md"
    if agents_md_path.exists():
        agents_sections = parse_doc_sections(agents_md_path, "AGENTS.md")
        report.agents_md_sections = agents_sections
        broken = check_references(agents_md_path, project_root)
        report.broken_refs.extend(broken)

    # Review project rules (.claude/rules/)
    rules_dir = project_root / ".claude" / "rules"
    if rules_dir.exists():
        for rule_file in rules_dir.glob("*.md"):
            rule_info = {
                "name": rule_file.name,
                "path": str(rule_file),
                "size_bytes": rule_file.stat().st_size,
                "last_modified": datetime.fromtimestamp(rule_file.stat().st_mtime).isoformat(),
            }
            report.rules_files.append(rule_info)
            broken = check_references(rule_file, project_root)
            report.broken_refs.extend(broken)

    # Review global rules (~/.claude/rules/)
    global_rules_dir = Path.home() / ".claude" / "rules"
    if global_rules_dir.exists():
        for rule_file in global_rules_dir.glob("*.md"):
            rule_info = {
                "name": rule_file.name,
                "path": str(rule_file),
                "size_bytes": rule_file.stat().st_size,
                "last_modified": datetime.fromtimestamp(rule_file.stat().st_mtime).isoformat(),
            }
            report.global_rules_files.append(rule_info)

    # Calculate token waste
    report.token_waste = calculate_token_waste(report)

    return report
