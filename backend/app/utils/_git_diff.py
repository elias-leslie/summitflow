"""Git diff and commit history helpers."""

from __future__ import annotations

import re
from pathlib import Path

from ..api.models.git_models import CommitInfo, DiffFile, DiffStats, SnapshotInfo
from ._git_core import run_git

_STATUS_CODE_MAP = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed"}
_LOG_FORMAT = "COMMIT_START%n%H%n%h%n%s%n%an%n%ae%n%cI"
_SNAPSHOT_TAG_PREFIX = "snapshot/pre-merge/"


def _parse_numstat(output: str) -> tuple[list[DiffFile], int, int]:
    """Parse git diff --numstat into DiffFile list plus totals."""
    files: list[DiffFile] = []
    total_add = total_del = 0
    for line in output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        adds = int(parts[0]) if parts[0] != "-" else 0
        dels = int(parts[1]) if parts[1] != "-" else 0
        total_add += adds
        total_del += dels
        files.append(DiffFile(path=parts[2], status="modified", additions=adds, deletions=dels, diff_content=""))
    return files, total_add, total_del


def _assign_diff_content(files: list[DiffFile], full_diff: str) -> None:
    """Split a unified diff into per-file chunks and assign to DiffFile objects."""
    file_map = {f.path: f for f in files}
    current_path: str | None = None
    current_lines: list[str] = []
    for line in full_diff.split("\n"):
        if line.startswith("diff --git"):
            if current_path and current_path in file_map:
                file_map[current_path].diff_content = "\n".join(current_lines)
            parts = line.split(" b/", 1)
            current_path = parts[1] if len(parts) > 1 else None
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_path and current_path in file_map:
        file_map[current_path].diff_content = "\n".join(current_lines)


def _apply_status_map(files: list[DiffFile], tree_output: str) -> None:
    """Update DiffFile.status using diff-tree name-status output."""
    status_map: dict[str, str] = {}
    for line in tree_output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            status_map[parts[-1]] = _STATUS_CODE_MAP.get(parts[0][0], "modified")
    for f in files:
        if f.path in status_map:
            f.status = status_map[f.path]


def get_task_diff(
    project_root: Path, pre_merge_sha: str, merge_sha: str
) -> tuple[list[DiffFile], DiffStats]:
    """Get file-level diffs between two SHAs."""
    sha_range = f"{pre_merge_sha}..{merge_sha}"
    files: list[DiffFile] = []
    total_add = total_del = 0

    numstat = run_git(["diff", "--numstat", sha_range], project_root)
    if numstat.returncode == 0:
        files, total_add, total_del = _parse_numstat(numstat.stdout)

    full_diff = run_git(["diff", sha_range], project_root)
    if full_diff.returncode == 0:
        _assign_diff_content(files, full_diff.stdout)

    tree_result = run_git(["diff-tree", "--no-commit-id", "-r", "--name-status", sha_range], project_root)
    if tree_result.returncode == 0:
        _apply_status_map(files, tree_result.stdout)

    return files, DiffStats(files_changed=len(files), additions=total_add, deletions=total_del)


def get_diff_stats(project_root: Path, sha_range: str) -> DiffStats:
    """Get aggregate diff statistics for a SHA range."""
    result = run_git(["diff", "--shortstat", sha_range], project_root)
    files_count = adds = dels = 0
    if result.returncode == 0 and result.stdout.strip():
        text = result.stdout.strip()
        m = re.search(r"(\d+) file", text)
        if m:
            files_count = int(m.group(1))
        m = re.search(r"(\d+) insertion", text)
        if m:
            adds = int(m.group(1))
        m = re.search(r"(\d+) deletion", text)
        if m:
            dels = int(m.group(1))
    return DiffStats(files_changed=files_count, additions=adds, deletions=dels)


def _parse_commit_block(block: str, repo_name: str) -> CommitInfo | None:
    """Parse a single COMMIT_START block into a CommitInfo."""
    lines = block.strip().split("\n")
    if len(lines) < 6:
        return None
    sha, short_sha, message, author_name, author_email, date = lines[:6]
    files_changed = insertions = deletions = 0
    for stat_line in lines[6:]:
        if not stat_line.strip():
            continue
        parts = stat_line.split("\t")
        if len(parts) == 3:
            files_changed += 1
            insertions += int(parts[0]) if parts[0] != "-" else 0
            deletions += int(parts[1]) if parts[1] != "-" else 0
    return CommitInfo(
        sha=sha, short_sha=short_sha, message=message,
        author_name=author_name, author_email=author_email, date=date,
        repo_name=repo_name, files_changed=files_changed,
        insertions=insertions, deletions=deletions,
    )


def get_recent_commits(repo_path: Path, limit: int = 30) -> list[CommitInfo]:
    """Get recent commits from a repository."""
    result = run_git(["log", f"-n{limit}", f"--format={_LOG_FORMAT}", "--numstat"], repo_path)
    if result.returncode != 0:
        return []
    repo_name = repo_path.name
    commits: list[CommitInfo] = []
    for block in result.stdout.split("COMMIT_START\n"):
        if not block.strip():
            continue
        commit = _parse_commit_block(block, repo_name)
        if commit:
            commits.append(commit)
    return commits


def _parse_snapshot_line(
    line: str, head_sha: str, repo_name: str, repo_path: Path
) -> SnapshotInfo | None:
    """Parse one snapshot tag line into a SnapshotInfo."""
    if not line.strip():
        return None
    parts = line.split("\t")
    if len(parts) < 4:
        return None
    tag_name, sha, short_sha, created_at = parts[0], parts[1], parts[2], parts[3]
    task_id = tag_name.replace(_SNAPSHOT_TAG_PREFIX, "")
    ar = run_git(["rev-list", "--count", f"{sha}..HEAD"], repo_path)
    commits_ahead = int(ar.stdout.strip()) if ar.returncode == 0 else 0
    return SnapshotInfo(
        task_id=task_id, task_title="", sha=sha, short_sha=short_sha,
        created_at=created_at, project_id="", repo_name=repo_name,
        is_current=sha == head_sha, commits_ahead=commits_ahead,
    )


def list_snapshots(repo_path: Path) -> list[SnapshotInfo]:
    """List pre-merge snapshot tags from a repository."""
    result = run_git(
        ["tag", "-l", f"{_SNAPSHOT_TAG_PREFIX}*", "--sort=-creatordate",
         "--format=%(refname:short)\t%(objectname)\t%(objectname:short)\t%(creatordate:iso-strict)"],
        repo_path,
    )
    if result.returncode != 0:
        return []
    hr = run_git(["rev-parse", "HEAD"], repo_path)
    head_sha = hr.stdout.strip() if hr.returncode == 0 else ""
    repo_name = repo_path.name
    snapshots: list[SnapshotInfo] = []
    for line in result.stdout.strip().split("\n"):
        snapshot = _parse_snapshot_line(line, head_sha, repo_name, repo_path)
        if snapshot:
            snapshots.append(snapshot)
    return snapshots


def revert_to_snapshot(repo_path: Path, sha: str, commits_ahead: int) -> str | None:
    """Revert HEAD to a snapshot point using git revert (preserves history)."""
    if commits_ahead <= 0:
        return None
    result = run_git(["revert", "--no-edit", f"HEAD~{commits_ahead}..HEAD"], repo_path)
    if result.returncode != 0:
        run_git(["revert", "--abort"], repo_path)
        return None
    head_result = run_git(["rev-parse", "HEAD"], repo_path)
    return head_result.stdout.strip() if head_result.returncode == 0 else None
