"""Implementation context - Context building for task execution.

Gathers rules, patterns, and observations for affected files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context_helpers import (
    filter_rules_by_files,
    get_observations_for_files,
    get_patterns_for_files,
)


def build_context(project_id: str, files: list[str]) -> dict[str, Any]:
    """Build context for a task based on affected files.

    Args:
        project_id: Project ID
        files: List of affected file paths

    Returns:
        Dict with files, rules, rule_contents, patterns, observations
    """
    rules = filter_rules_by_files(files)

    # Read rule contents
    rule_contents: dict[str, str] = {}
    for rule in rules:
        for rules_dir in [
            Path("/home/kasadis/summitflow/.claude/rules"),
            Path("/home/kasadis/.claude/rules"),
        ]:
            rule_path = rules_dir / rule
            if rule_path.exists():
                rule_contents[rule] = rule_path.read_text()
                break

    patterns = get_patterns_for_files(project_id, files)
    observations = get_observations_for_files(project_id, files)

    return {
        "files": files,
        "rules": rules,
        "rule_contents": rule_contents,
        "patterns": patterns,
        "observations": observations,
    }
