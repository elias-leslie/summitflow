"""Internal helpers for destructive_path_guard — not part of the public API."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ..utils import safe_subprocess

_ENV_SESSION_ID_KEYS = (
    "ST_SESSION_ID",
    "AGENT_HUB_SESSION_ID",
    "CODEX_THREAD_ID",
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
)
_INDEX_PROJECT_RE = re.compile(r"^\s*project\s*:\s*[\"']?([A-Za-z0-9_.-]+)[\"']?\s*$", re.MULTILINE)


def resolve_current_session_id(explicit_session_id: str | None = None) -> str | None:
    """Return the current live session id from args or wrapper env."""
    if explicit_session_id:
        return explicit_session_id
    for env_key in _ENV_SESSION_ID_KEYS:
        env_value = os.getenv(env_key)
        if env_value:
            return env_value
    return None


def derive_task_id(session: dict[str, object]) -> str | None:
    """Infer the task id associated with a live lane session."""
    for field_key in ("task_id", "external_id"):
        field_value = session.get(field_key)
        if isinstance(field_value, str) and field_value.startswith("task-"):
            return field_value
    branch = session.get("current_branch")
    if not isinstance(branch, str) or not branch:
        return None
    branch_prefix = branch.split("/", 1)[0]
    return branch_prefix if branch_prefix.startswith("task-") else None


def session_checkout_root(session: dict[str, object]) -> Path | None:
    """Return the normalized checkout root for a live owner session, if present."""
    for path_key in ("working_dir", "checkout_path", "repo_root"):
        path_value = session.get(path_key)
        if not isinstance(path_value, str) or not path_value:
            continue
        try:
            return Path(path_value).resolve()
        except OSError:
            return Path(path_value)
    return None


def resolve_project_id(repo_root: Path) -> str | None:
    """Infer the managed project id from local repo metadata."""
    index_path = repo_root / ".index.yaml"
    if index_path.exists():
        try:
            match = _INDEX_PROJECT_RE.search(index_path.read_text(encoding="utf-8"))
        except OSError:
            match = None
        if match:
            return match.group(1).strip()
    parts = repo_root.parts
    if len(parts) >= 2 and parts[-2] == "projects":
        return repo_root.name
    if len(parts) >= 3 and parts[-3] == "lanes":
        return parts[-2]
    return None


def current_branch(repo_root: Path) -> str | None:
    """Return the current git branch for repo_root."""
    try:
        result = safe_subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return result.stdout.strip() or None


def parse_null_separated_diff_output(raw_bytes: bytes) -> list[str]:
    """Extract old paths from null-separated git diff --name-status -z output."""
    null_separated_parts = raw_bytes.split(b"\0")
    extracted_paths: list[str] = []
    entry_index = 0
    while entry_index < len(null_separated_parts) and null_separated_parts[entry_index]:
        status_code = null_separated_parts[entry_index].decode("utf-8", errors="replace")[:1]
        entry_index += 1
        if status_code == "D":
            if entry_index < len(null_separated_parts) and null_separated_parts[entry_index]:
                extracted_paths.append(null_separated_parts[entry_index].decode("utf-8", errors="replace"))
            entry_index += 1
        elif status_code == "R":
            if entry_index < len(null_separated_parts) and null_separated_parts[entry_index]:
                extracted_paths.append(null_separated_parts[entry_index].decode("utf-8", errors="replace"))
            entry_index += 2
        else:
            entry_index += 1
    return extracted_paths


def get_session_field_str(session: dict[str, object], *keys: str) -> str | None:
    """Return the first non-empty string value for keys from a session dict, or None."""
    return str(next((session.get(k) for k in keys if session.get(k)), "") or "") or None


def same_checkout_sessions(
    owner_sessions: Sequence[dict[str, object]], repo_root: Path,
) -> list[dict[str, object]]:
    """Return live owner sessions sharing the current checkout root."""
    resolved_root = repo_root.resolve()
    return [
        sess for sess in owner_sessions
        if (sess_root := session_checkout_root(sess)) is not None
        and sess_root == resolved_root
    ]


def infer_self_session_ids(
    owner_sessions: Sequence[dict[str, object]],
    *,
    current_branch: str | None,
    current_session_id: str | None,
) -> set[str]:
    """Return owner session ids that should be treated as the current session."""
    return {current_session_id} if current_session_id else set()
