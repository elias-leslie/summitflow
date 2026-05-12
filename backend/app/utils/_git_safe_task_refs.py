"""Safe task-ref cleanup helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SafeTaskRef:
    """Task ref that is safe to delete because base already contains its work."""

    name: str
    ref: str
    kind: str
    reason: str
    remote: str = "origin"


def _git_branches_module():
    """Import branch-query helpers lazily to avoid module-level cycles."""
    from . import _git_branches

    return _git_branches


def _is_task_ref_name(name: str) -> bool:
    return name.startswith("task/") or (name.startswith("task-") and "/" in name)


def _base_ref(repo_path: Path, base_branch: str, remote: str) -> str:
    git_branches = _git_branches_module()
    remote_base = f"{remote}/{base_branch}"
    result = git_branches.run_git(["rev-parse", "--verify", "--quiet", remote_base], repo_path)
    return remote_base if result.returncode == 0 else base_branch


def _task_ref_reason(repo_path: Path, ref: str, base_ref: str) -> str | None:
    git_branches = _git_branches_module()
    merged = git_branches.run_git(["merge-base", "--is-ancestor", ref, base_ref], repo_path)
    if merged.returncode == 0:
        return "merged"
    diff = git_branches.run_git(["diff", "--quiet", base_ref, ref], repo_path)
    if diff.returncode == 0:
        return "equivalent"
    if not git_branches._branch_has_unapplied_patch(repo_path, ref, base_ref):
        return "patch_applied"
    return None


def list_safe_task_refs(
    repo_path: Path,
    *,
    base_branch: str | None = None,
    remote: str = "origin",
) -> list[SafeTaskRef]:
    """Return local and remote task refs whose work is already on base."""
    git_branches = _git_branches_module()
    base_branch = base_branch or git_branches._detect_base_branch(repo_path)
    base_ref = _base_ref(repo_path, base_branch, remote)
    refs: list[SafeTaskRef] = []

    local = git_branches.run_git(["for-each-ref", "--format=%(refname:short)", "refs/heads"], repo_path)
    if local.returncode == 0:
        for name in local.stdout.splitlines():
            branch_name = name.strip()
            if not branch_name or branch_name == base_branch or not _is_task_ref_name(branch_name):
                continue
            reason = _task_ref_reason(repo_path, branch_name, base_ref)
            if reason:
                refs.append(
                    SafeTaskRef(
                        name=branch_name,
                        ref=f"refs/heads/{branch_name}",
                        kind="local",
                        reason=reason,
                    )
                )

    remote_prefix = f"{remote}/"
    remote_refs = git_branches.run_git(
        ["for-each-ref", "--format=%(refname:short)", f"refs/remotes/{remote}"],
        repo_path,
    )
    if remote_refs.returncode == 0:
        for short_name in remote_refs.stdout.splitlines():
            remote_name = short_name.strip()
            if not remote_name or remote_name in {remote, f"{remote}/HEAD"}:
                continue
            if not remote_name.startswith(remote_prefix):
                continue
            branch_name = remote_name.removeprefix(remote_prefix)
            if branch_name == base_branch or not _is_task_ref_name(branch_name):
                continue
            reason = _task_ref_reason(repo_path, remote_name, base_ref)
            if reason:
                refs.append(
                    SafeTaskRef(
                        name=branch_name,
                        ref=f"refs/remotes/{remote}/{branch_name}",
                        kind="remote",
                        reason=reason,
                        remote=remote,
                    )
                )
    return refs


def prune_safe_task_refs(
    repo_path: Path,
    *,
    base_branch: str | None = None,
    remote: str = "origin",
    dry_run: bool = False,
) -> tuple[int, int]:
    """Delete local and remote task refs whose work is already on base."""
    git_branches = _git_branches_module()
    refs = list_safe_task_refs(repo_path, base_branch=base_branch, remote=remote)
    local_names = sorted({ref.name for ref in refs if ref.kind == "local"})
    remote_names = sorted({ref.name for ref in refs if ref.kind == "remote"})
    if dry_run:
        return len(local_names), len(remote_names)

    removed_local = 0
    base_branch = base_branch or git_branches._detect_base_branch(repo_path)
    current = git_branches.run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    current_branch = current.stdout.strip() if current.returncode == 0 else ""
    for branch_name in local_names:
        if current_branch == branch_name:
            if git_branches.run_git(["checkout", base_branch], repo_path).returncode != 0:
                continue
            current_branch = base_branch
        if git_branches.run_git(["branch", "-D", branch_name], repo_path).returncode == 0:
            removed_local += 1

    removed_remote = 0
    for branch_name in remote_names:
        result = git_branches.run_git(["push", remote, "--delete", branch_name], repo_path)
        detail = f"{result.stdout}\n{result.stderr}"
        if result.returncode == 0 or "remote ref does not exist" in detail:
            removed_remote += 1
    if removed_remote:
        git_branches.run_git(["fetch", remote, "--prune"], repo_path)
    return removed_local, removed_remote
