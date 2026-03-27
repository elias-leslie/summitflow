"""Git context helpers for codex-session-sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_LOG_SINCE = "12 hours ago"
GIT_LOG_LIMIT = 10
GIT_FILTER_PREFIXES = ("chore: auto-fix", "chore(.index")


def build_project_context(cwd: Path) -> dict[str, object] | None:
    try:
        project_dir = subprocess.check_output(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    project_path = Path(project_dir)
    branch = subprocess.run(
        ["git", "-C", str(project_path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    raw_log = subprocess.run(
        ["git", "-C", str(project_path), "log", "--oneline",
         f"--since={GIT_LOG_SINCE}", "--no-merges", "--format=%h %s"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    git_lines = [
        ln for ln in raw_log.splitlines()
        if not any(ln.startswith(p) or p in ln for p in GIT_FILTER_PREFIXES)
    ]
    return {
        "project_dir": project_path,
        "project_id": project_path.name,
        "branch": branch,
        "is_worktree": (project_path / ".git").is_file(),
        "repo_root": str(project_path),
        "git_context": "\n".join(git_lines[:GIT_LOG_LIMIT]),
    }
