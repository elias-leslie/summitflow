"""Best-effort publication of existing default-branch commits before backups.

The scheduler opts in through backup_publish_before_backup. Every result permits
backup capture to continue; failed/pending publication stays retryable through
the existing completed-backup verification record. This helper creates no commit
and never modifies the worktree, index, branch or upstream configuration.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from ..services.git.utils import network_repository_identity, push_captured_head_to_upstream
from ..utils import safe_subprocess


class _InspectionFailed(RuntimeError):
    """Local inspection failed; no raw Git diagnostic escapes to records."""


def _git(project: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    try:
        return safe_subprocess.run(
            ["git", "-C", str(project), *arguments], capture_output=True,
            text=True, stdin=subprocess.DEVNULL, env=environment, timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _InspectionFailed from exc


def _value(project: Path, *arguments: str) -> str:
    result = _git(project, *arguments)
    if result.returncode != 0:
        raise _InspectionFailed
    return result.stdout.strip()


def _acceptance_for_head(project: Path, head: str) -> dict[str, Any]:
    """Reuse the canonical exact-source validator; never run a daily gate."""
    try:
        # The canonical validator reads Git blobs. In a partial clone that can
        # lazily fetch, so omit optional receipt reuse rather than let an offline
        # validation wait outside the bounded publication transport.
        partial = _git(project, "config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$")
        if partial.returncode == 0:
            return {"state": "unavailable", "reason": "partial_clone"}
        common = Path(_value(project, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        candidates = sorted((common / "st" / "acceptance").glob("*.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)[:64]
        matched = False
        for artifact in candidates:
            if artifact.is_symlink() or not artifact.is_file() or artifact.stat().st_size > 4 * 1024 * 1024:
                continue
            try:
                receipt = json.loads(artifact.read_text())
                if not isinstance(receipt, dict) or not isinstance(receipt.get("source"), dict) or receipt["source"].get("commit") != head:
                    continue
                matched = True
                from cli.lib.acceptance import validate_acceptance_receipt

                validated = validate_acceptance_receipt(project, artifact, sha=head)
                return {"state": "reused", "acceptance_id": validated["acceptance_id"]}
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                continue
        return {"state": "invalid" if matched else "missing"}
    except (ImportError, OSError, RuntimeError):
        return {"state": "unavailable"}


def publish_source_before_backup(source: dict[str, Any]) -> dict[str, Any]:
    """Publish captured committed HEAD to its existing matching main upstream.

    Caller supplies an enabled registered source and owns feature-flag gating.
    Only main/master to the identically named configured upstream is eligible.
    Network failure is sanitized and never prevents backup or stages WIP.
    """
    result: dict[str, Any] = {
        "source_id": source.get("id"), "status": "skipped", "attempted": False,
        "backup_can_continue": True,
    }

    def outcome(status: str, reason: str) -> dict[str, Any]:
        return {**result, "status": status, "reason": reason}

    if source.get("source_type") != "project":
        return outcome("skipped", "non_project_source")
    if not source.get("id") or not source.get("path"):
        return outcome("skipped", "unregistered_source")
    if source.get("enabled") is not True:
        return outcome("skipped", "disabled_source")
    try:
        project = Path(source["path"]).expanduser().resolve(strict=True)
        if not project.is_dir():
            return outcome("skipped", "not_project_directory")
        if (project / ".jj").exists() or (project / ".jj").is_symlink():
            return outcome("skipped", "jj_repository")
        top = _git(project, "rev-parse", "--show-toplevel")
        if top.returncode != 0:
            return outcome("skipped", "not_git_repository")
        if Path(top.stdout.strip()).resolve() != project:
            return outcome("skipped", "repository_root_mismatch")
        symbolic = _git(project, "symbolic-ref", "--quiet", "--short", "HEAD")
        if symbolic.returncode != 0:
            return outcome("skipped", "detached_head")
        branch = symbolic.stdout.strip()
        if branch not in {"main", "master"}:
            return outcome("skipped", "non_default_branch")
        head_result = _git(project, "rev-parse", "--verify", "HEAD^{commit}")
        if head_result.returncode != 0:
            return outcome("skipped", "unborn_head")
        head = head_result.stdout.strip()
        route = _value(project, "for-each-ref", "--format=%(upstream)%00%(upstream:remotename)%00%(upstream:remoteref)", f"refs/heads/{branch}").split("\0")
        if len(route) != 3 or not all(route):
            return outcome("skipped", "no_existing_upstream")
        tracking_ref, remote, upstream_ref = route
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", remote) or upstream_ref != f"refs/heads/{branch}" or tracking_ref != f"refs/remotes/{remote}/{branch}":
            return outcome("skipped", "incorrect_upstream_route")
        if _value(project, "config", "--get-all", f"branch.{branch}.remote").splitlines() != [remote] or _value(project, "config", "--get-all", f"branch.{branch}.merge").splitlines() != [upstream_ref]:
            return outcome("skipped", "ambiguous_upstream_route")
        fetch_urls = _value(project, "remote", "get-url", "--all", remote).splitlines()
        push_urls = _value(project, "remote", "get-url", "--push", "--all", remote).splitlines()
        if len(fetch_urls) != 1 or len(push_urls) != 1:
            return outcome("skipped", "ambiguous_remote_route")
        identity = network_repository_identity(fetch_urls[0])
        if identity is None or network_repository_identity(push_urls[0]) != identity:
            return outcome("skipped", "unsafe_remote_route")
        mirror = _git(project, "config", "--bool", "--get", f"remote.{remote}.mirror")
        if mirror.returncode not in {0, 1}:
            return outcome("skipped", "uncertain_mirror_configuration")
        if mirror.returncode == 0 and mirror.stdout.strip() == "true":
            return outcome("skipped", "mirror_remote")
        upstream = _git(project, "rev-parse", "--verify", f"{tracking_ref}^{{commit}}")
        if upstream.returncode != 0:
            return outcome("skipped", "upstream_commit_unavailable")
        upstream_head = upstream.stdout.strip()
        counts = _value(project, "rev-list", "--left-right", "--count", f"{upstream_head}...{head}").split()
        behind, ahead = map(int, counts)
        result.update(head=head, branch=branch, remote=remote, upstream_ref=upstream_ref, ahead=ahead)
        if not ahead:
            return outcome("up_to_date", "no_unpublished_commits")
        if behind:
            return outcome("failed", "upstream_diverged")
        result["acceptance"] = _acceptance_for_head(project, head)
        if _value(project, "rev-parse", "--verify", "HEAD^{commit}") != head or _value(project, "symbolic-ref", "--quiet", "--short", "HEAD") != branch or _value(project, "remote", "get-url", "--push", "--all", remote).splitlines() != push_urls:
            return outcome("pending", "repository_changed")
        ssh = _git(project, "config", "--get", "core.sshCommand")
        ssh_command = os.environ.get("GIT_SSH_COMMAND") or (ssh.stdout.strip() if ssh.returncode == 0 else "ssh")
        pushed = push_captured_head_to_upstream(project, head, upstream_ref, push_urls[0], ssh_command=ssh_command)
        result.update(pushed)
        if pushed["status"] == "published":
            # Ordinary named-remote Git push updates this same tracking ref.
            # Compare-and-swap preserves a concurrent fetch's newer observation.
            try:
                observed = _git(project, "update-ref", tracking_ref, head, upstream_head)
                result["tracking_ref_updated"] = observed.returncode == 0
            except _InspectionFailed:
                result["tracking_ref_updated"] = False
        return {**result, "backup_can_continue": True}
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.SubprocessError):
        return outcome("failed", "publication_inspection_unavailable")
