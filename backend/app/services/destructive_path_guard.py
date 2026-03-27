"""Block destructive same-checkout path actions when another live session owns them."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from ._lane_inventory import fetch_live_project_inventory
from ._lane_scope import load_live_lane_scope
from ._scope_paths import normalize_scope_values

_DESTRUCTIVE_DIFF_FILTER = "DR"
_ENV_SESSION_ID_KEYS = (
    "ST_SESSION_ID",
    "AGENT_HUB_SESSION_ID",
    "CODEX_THREAD_ID",
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
)
_INDEX_PROJECT_RE = re.compile(r"^\s*project\s*:\s*[\"']?([A-Za-z0-9_.-]+)[\"']?\s*$", re.MULTILINE)


class DestructivePathGuardError(RuntimeError):
    """Raised when destructive-path ownership cannot be evaluated safely."""


@dataclass(frozen=True)
class GuardConflict:
    """A foreign live session blocking a destructive path action."""

    session_id: str
    task_id: str | None
    branch: str | None
    worktree_path: str | None
    reason: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class GuardDecision:
    """Result of evaluating destructive paths against live ownership."""

    blocked: bool
    project_id: str | None
    repo_root: str
    current_session_id: str | None
    destructive_paths: tuple[str, ...]
    conflicts: tuple[GuardConflict, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "blocked": self.blocked,
            "project_id": self.project_id,
            "repo_root": self.repo_root,
            "current_session_id": self.current_session_id,
            "destructive_paths": list(self.destructive_paths),
            "conflicts": [asdict(conflict) for conflict in self.conflicts],
        }


def _resolve_current_session_id(explicit_session_id: str | None = None) -> str | None:
    """Return the current live session id from args or wrapper env."""
    if explicit_session_id:
        return explicit_session_id
    for key in _ENV_SESSION_ID_KEYS:
        value = os.getenv(key)
        if value:
            return value
    return None


def _derive_task_id(session: dict[str, object]) -> str | None:
    """Infer the task id associated with a live lane session."""
    for key in ("task_id", "external_id"):
        raw = session.get(key)
        if isinstance(raw, str) and raw.startswith("task-"):
            return raw
    branch = session.get("current_branch")
    if not isinstance(branch, str) or not branch:
        return None
    prefix = branch.split("/", 1)[0]
    return prefix if prefix.startswith("task-") else None


def _session_checkout_root(session: dict[str, object]) -> Path | None:
    """Return the normalized checkout root for a live owner session, if present."""
    for key in ("worktree_path", "working_dir"):
        raw = session.get(key)
        if not isinstance(raw, str) or not raw:
            continue
        try:
            return Path(raw).resolve()
        except OSError:
            return Path(raw)
    return None


def _resolve_project_id(repo_root: Path) -> str | None:
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
    if len(parts) >= 3 and parts[-3] in {"worktrees", "lanes"}:
        return parts[-2]
    return None


def _current_branch(repo_root: Path) -> str | None:
    """Return the current git branch for repo_root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    branch = result.stdout.strip()
    return branch or None


def staged_destructive_paths(repo_root: Path) -> list[str]:
    """Return repo-relative staged destructive paths (delete or rename-away)."""
    try:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--name-status",
                "--find-renames",
                "--diff-filter",
                _DESTRUCTIVE_DIFF_FILTER,
                "-z",
            ],
            cwd=repo_root,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise DestructivePathGuardError(
            f"Failed to inspect staged destructive paths in {repo_root}: {exc}"
        ) from exc

    if not result.stdout:
        return []

    parts = result.stdout.split(b"\0")
    paths: list[str] = []
    idx = 0
    while idx < len(parts) and parts[idx]:
        status = parts[idx].decode("utf-8", errors="replace")
        idx += 1
        code = status[:1]
        if code == "D":
            if idx < len(parts) and parts[idx]:
                path = parts[idx].decode("utf-8", errors="replace")
                paths.append(path)
            idx += 1
            continue
        if code == "R":
            if idx < len(parts) and parts[idx]:
                old_path = parts[idx].decode("utf-8", errors="replace")
                paths.append(old_path)
            idx += 2
            continue
        idx += 1

    return sorted(normalize_scope_values(paths))


def _same_checkout_sessions(
    owner_sessions: Sequence[dict[str, object]],
    repo_root: Path,
) -> list[dict[str, object]]:
    """Return live owners sharing the current checkout root."""
    resolved_root = repo_root.resolve()
    return [
        session
        for session in owner_sessions
        if (session_root := _session_checkout_root(session)) is not None
        and session_root == resolved_root
    ]


def _infer_self_session_ids(
    owner_sessions: Sequence[dict[str, object]],
    *,
    current_branch: str | None,
    current_session_id: str | None,
) -> set[str]:
    """Return owner session ids that should be treated as the current session."""
    if current_session_id:
        return {current_session_id}
    return set()


def evaluate_destructive_paths(
    repo_root: Path,
    destructive_paths: Sequence[str],
    owner_sessions: Sequence[dict[str, object]],
    *,
    project_id: str | None = None,
    current_branch: str | None = None,
    current_session_id: str | None = None,
) -> GuardDecision:
    """Evaluate destructive repo-relative paths against same-checkout live owners."""
    repo_root = repo_root.resolve()
    normalized_paths = tuple(sorted(normalize_scope_values(list(destructive_paths))))
    resolved_session_id = _resolve_current_session_id(current_session_id)
    if not normalized_paths:
        return GuardDecision(
            blocked=False,
            project_id=project_id,
            repo_root=str(repo_root),
            current_session_id=resolved_session_id,
            destructive_paths=(),
            conflicts=(),
        )

    shared_checkout = _same_checkout_sessions(owner_sessions, repo_root)
    if not shared_checkout:
        return GuardDecision(
            blocked=False,
            project_id=project_id,
            repo_root=str(repo_root),
            current_session_id=resolved_session_id,
            destructive_paths=normalized_paths,
            conflicts=(),
        )

    self_session_ids = _infer_self_session_ids(
        shared_checkout,
        current_branch=current_branch,
        current_session_id=resolved_session_id,
    )
    target_set = set(normalized_paths)
    conflicts: list[GuardConflict] = []

    for session in shared_checkout:
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id or session_id in self_session_ids:
            continue

        task_id = _derive_task_id(session)
        scope = load_live_lane_scope(session, task_id) if task_id else None
        if scope is None:
            conflicts.append(
                GuardConflict(
                    session_id=session_id,
                    task_id=task_id,
                    branch=str(session.get("current_branch") or "") or None,
                    worktree_path=str(session.get("worktree_path") or session.get("working_dir") or "") or None,
                    reason="unknown_scope",
                    paths=normalized_paths,
                )
            )
            continue

        overlap_paths = tuple(sorted(target_set & (scope.write_paths | scope.read_paths)))
        if not overlap_paths:
            continue
        conflicts.append(
            GuardConflict(
                session_id=session_id,
                task_id=task_id,
                branch=str(session.get("current_branch") or "") or None,
                worktree_path=str(session.get("worktree_path") or session.get("working_dir") or "") or None,
                reason="scope_overlap",
                paths=overlap_paths,
            )
        )

    return GuardDecision(
        blocked=bool(conflicts),
        project_id=project_id,
        repo_root=str(repo_root),
        current_session_id=resolved_session_id,
        destructive_paths=normalized_paths,
        conflicts=tuple(conflicts),
    )


def check_destructive_paths(
    repo_root: Path,
    destructive_paths: Sequence[str],
    *,
    project_id: str | None = None,
    current_branch: str | None = None,
    current_session_id: str | None = None,
) -> GuardDecision:
    """Resolve live ownership and return whether destructive paths are safe."""
    repo_root = repo_root.resolve()
    resolved_project_id = project_id or _resolve_project_id(repo_root)
    resolved_session_id = _resolve_current_session_id(current_session_id)
    branch = current_branch or _current_branch(repo_root)

    normalized_paths = tuple(sorted(normalize_scope_values(list(destructive_paths))))
    if not normalized_paths or not resolved_project_id:
        return GuardDecision(
            blocked=False,
            project_id=resolved_project_id,
            repo_root=str(repo_root),
            current_session_id=resolved_session_id,
            destructive_paths=normalized_paths,
            conflicts=(),
        )

    try:
        owner_sessions, _ = fetch_live_project_inventory(resolved_project_id)
    except Exception as exc:
        raise DestructivePathGuardError(
            f"Failed to verify live ownership for project {resolved_project_id}: {exc}"
        ) from exc

    return evaluate_destructive_paths(
        repo_root,
        normalized_paths,
        owner_sessions,
        project_id=resolved_project_id,
        current_branch=branch,
        current_session_id=resolved_session_id,
    )


def format_guard_report(decision: GuardDecision) -> str:
    """Return a compact human-readable block report."""
    lines = [
        "Refusing destructive path action: another live session shares this checkout.",
        f"repo: {decision.repo_root}",
    ]
    if decision.project_id:
        lines.append(f"project: {decision.project_id}")
    if decision.current_session_id:
        lines.append(f"current_session: {decision.current_session_id[:8]}")
    lines.append(f"targets: {', '.join(decision.destructive_paths)}")
    for conflict in decision.conflicts:
        prefix = "AMBIG" if conflict.reason == "unknown_scope" else "OWNED"
        parts = [
            prefix,
            conflict.session_id[:8],
            conflict.task_id or "-",
            conflict.branch or "-",
        ]
        if conflict.reason == "unknown_scope":
            parts.append("scope=unknown")
        else:
            parts.append(f"paths={','.join(conflict.paths)}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Git/worktree root to inspect")
    parser.add_argument("--project-id", help="Optional project id override")
    parser.add_argument("--current-session-id", help="Explicit current live session id")
    parser.add_argument("--staged-git", action="store_true", help="Inspect staged destructive git paths")
    parser.add_argument("--path", dest="paths", action="append", default=[], help="Explicit repo-relative destructive path")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human text")
    args = parser.parse_args(argv)
    if not args.staged_git and not args.paths:
        parser.error("pass --staged-git or at least one --path")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for shell callers like commit.sh."""
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        destructive_paths = staged_destructive_paths(repo_root) if args.staged_git else list(args.paths)
        decision = check_destructive_paths(
            repo_root,
            destructive_paths,
            project_id=args.project_id,
            current_session_id=args.current_session_id,
        )
    except DestructivePathGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(decision.to_dict(), sort_keys=True))
    elif decision.blocked:
        print(format_guard_report(decision))
    return 2 if decision.blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
