"""Block destructive same-checkout path actions when another live session owns them."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from ._destructive_path_guard_helpers import (
    current_branch as _current_branch,
)
from ._destructive_path_guard_helpers import (
    derive_task_id as _derive_task_id,
)
from ._destructive_path_guard_helpers import (
    get_session_field_str as _get_session_field_str,
)
from ._destructive_path_guard_helpers import (
    infer_self_session_ids as _infer_self_session_ids,
)
from ._destructive_path_guard_helpers import (
    parse_null_separated_diff_output as _parse_null_separated_diff_output,
)
from ._destructive_path_guard_helpers import (
    resolve_current_session_id as _resolve_current_session_id,
)
from ._destructive_path_guard_helpers import (
    resolve_project_id as _resolve_project_id,
)
from ._destructive_path_guard_helpers import (
    same_checkout_sessions as _same_checkout_sessions,
)
from ._lane_inventory import fetch_live_project_inventory
from ._lane_scope import load_live_lane_scope
from ._scope_paths import normalize_scope_values

_DESTRUCTIVE_DIFF_FILTER = "DR"


class DestructivePathGuardError(RuntimeError):
    """Raised when destructive-path ownership cannot be evaluated safely."""


@dataclass(frozen=True)
class GuardConflict:
    """A foreign live session blocking a destructive path action."""
    session_id: str
    task_id: str | None
    branch: str | None
    working_dir: str | None
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


def staged_destructive_paths(repo_root: Path) -> list[str]:
    """Return repo-relative staged destructive paths (delete or rename-away)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-status", "--find-renames",
             "--diff-filter", _DESTRUCTIVE_DIFF_FILTER, "-z"],
            cwd=repo_root, capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise DestructivePathGuardError(
            f"Failed to inspect staged destructive paths in {repo_root}: {exc}"
        ) from exc
    if not result.stdout:
        return []
    return sorted(normalize_scope_values(_parse_null_separated_diff_output(result.stdout)))


def _build_session_conflict(
    session: dict[str, object],
    session_id: str,
    task_id: str | None,
    target_path_set: set[str],
) -> GuardConflict | None:
    """Evaluate one foreign session and return a conflict if paths overlap, else None."""
    branch = _get_session_field_str(session, "current_branch")
    working_dir = _get_session_field_str(session, "working_dir")
    scope = load_live_lane_scope(session, task_id)
    if scope is None:
        return GuardConflict(
            session_id=session_id, task_id=task_id, branch=branch, working_dir=working_dir,
            reason="unknown_scope", paths=tuple(sorted(target_path_set)),
        )
    overlap_paths = tuple(sorted(target_path_set & (scope.write_paths | scope.read_paths)))
    if not overlap_paths:
        return None
    return GuardConflict(
        session_id=session_id, task_id=task_id, branch=branch, working_dir=working_dir,
        reason="scope_overlap", paths=overlap_paths,
    )


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

    def _clear_decision(paths: tuple[str, ...]) -> GuardDecision:
        return GuardDecision(
            blocked=False, project_id=project_id, repo_root=str(repo_root),
            current_session_id=resolved_session_id, destructive_paths=paths, conflicts=(),
        )

    if not normalized_paths:
        return _clear_decision(())
    shared_checkout = _same_checkout_sessions(owner_sessions, repo_root)
    if not shared_checkout:
        return _clear_decision(normalized_paths)

    self_session_ids = _infer_self_session_ids(
        shared_checkout, current_branch=current_branch, current_session_id=resolved_session_id,
    )
    target_path_set = set(normalized_paths)
    conflicts: list[GuardConflict] = []
    for session in shared_checkout:
        session_id = session.get("id")
        if not isinstance(session_id, str) or not session_id or session_id in self_session_ids:
            continue
        task_id = _derive_task_id(session)
        conflict = _build_session_conflict(session, session_id, task_id, target_path_set)
        if conflict is not None:
            conflicts.append(conflict)

    return GuardDecision(
        blocked=bool(conflicts), project_id=project_id, repo_root=str(repo_root),
        current_session_id=resolved_session_id, destructive_paths=normalized_paths,
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
            blocked=False, project_id=resolved_project_id, repo_root=str(repo_root),
            current_session_id=resolved_session_id, destructive_paths=normalized_paths, conflicts=(),
        )
    try:
        owner_sessions, _ = fetch_live_project_inventory(resolved_project_id)
    except Exception as exc:
        raise DestructivePathGuardError(
            f"Failed to verify live ownership for project {resolved_project_id}: {exc}"
        ) from exc

    return evaluate_destructive_paths(
        repo_root, normalized_paths, owner_sessions,
        project_id=resolved_project_id, current_branch=branch, current_session_id=resolved_session_id,
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
        conflict_parts = [prefix, conflict.session_id[:8], conflict.task_id or "-", conflict.branch or "-"]
        conflict_parts.append("scope=unknown" if conflict.reason == "unknown_scope" else f"paths={','.join(conflict.paths)}")
        lines.append(" | ".join(conflict_parts))
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Git checkout root to inspect")
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
    """CLI entrypoint for shell callers such as st git commit."""
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        destructive_paths = staged_destructive_paths(repo_root) if args.staged_git else list(args.paths)
        decision = check_destructive_paths(
            repo_root, destructive_paths,
            project_id=args.project_id, current_session_id=args.current_session_id,
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
