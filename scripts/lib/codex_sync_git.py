"""Git context helpers for codex-session-sync."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

GIT_LOG_SINCE = "12 hours ago"
GIT_LOG_LIMIT = 10
GIT_FILTER_PREFIXES = ("chore: auto-fix", "chore(.index")
PROJECT_IDENTITY_NAME = "project.identity.json"


def _load_project_identity(project_path: Path) -> tuple[str, list[str]]:
    manifest_path = project_path / PROJECT_IDENTITY_NAME
    if not manifest_path.exists():
        return project_path.name, []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return project_path.name, []
    project = payload.get("project")
    if not isinstance(project, dict):
        return project_path.name, []

    canonical = str(project.get("id") or project_path.name)
    aliases: list[str] = []
    for key in ("legacy_ids", "repo_aliases"):
        values = project.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, str) or not value or value == canonical or value in aliases:
                continue
            aliases.append(value)
    return canonical, aliases


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
    project_id, project_aliases = _load_project_identity(project_path)
    return {
        "project_dir": project_path,
        "project_id": project_id,
        "project_aliases": project_aliases,
        "branch": branch,
        "is_worktree": (project_path / ".git").is_file(),
        "repo_root": str(project_path),
        "git_context": "\n".join(git_lines[:GIT_LOG_LIMIT]),
    }
