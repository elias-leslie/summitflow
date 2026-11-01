"""Flag hand-written or tool-generated agent instruction files in a managed project.

Agent context is delivered by Agent Hub only. A new AGENTS.md, CLAUDE.md, GEMINI.md or
editor rules file beside the code is a second, unmanaged context channel.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

# Where harnesses and generators look: the project root plus the usual app subdirs.
_SEARCH_DIRS = (".", "frontend", "backend")
_INSTRUCTION_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".claude/CLAUDE.md",
    ".claude/rules",
    ".cursor/rules",
    ".cursorrules",
    ".github/copilot-instructions.md",
)


def _allowed(root: Path) -> set[str]:
    """Paths a project accepts, from `.st-check.toml`: [agent_context] allow = ["frontend/CLAUDE.md"]."""
    try:
        data = tomllib.loads((root / ".st-check.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    section = data.get("agent_context")
    allow = section.get("allow") if isinstance(section, dict) else None
    return {item for item in allow if isinstance(item, str)} if isinstance(allow, list) else set()


def run_agent_context_files_check(root: Path) -> int:
    allowed = _allowed(root)
    found = sorted(
        rel
        for base in _SEARCH_DIRS
        for name in _INSTRUCTION_PATHS
        if (rel := (Path(base) / name).as_posix()) not in allowed and (root / rel).exists()
    )
    if found:
        print(
            f"AGENTCTX:FAIL:{','.join(found)}|hint:agent context is delivered by Agent Hub only; "
            "move the rule into project memory and delete the file, or list it under "
            "[agent_context] allow in .st-check.toml"
        )
        return 1
    print("AGENTCTX:OK")
    return 0
