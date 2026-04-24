"""Diff gate — block task completion when branch has zero meaningful changes.

Prevents false completions where agents mark tasks done without making code changes.
"""

from __future__ import annotations

import contextlib
import subprocess
from dataclasses import dataclass

from ....logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class DiffGateResult:
    """Result of the diff gate check."""

    passed: bool
    files_changed: int
    insertions: int
    deletions: int
    summary: str


def check_diff_gate(
    project_path: str,
    *,
    head_ref: str = "HEAD",
    base_ref: str = "main",
) -> DiffGateResult:
    """Check whether the task branch has meaningful changes vs base (main).

    Runs git diff --stat to compare a task ref against the merge-base with main.
    Returns a DiffGateResult indicating whether the gate passed.
    """
    try:
        merge_base = _get_merge_base(project_path, head_ref, base_ref)
        if not merge_base:
            return DiffGateResult(
                passed=True,
                files_changed=0,
                insertions=0,
                deletions=0,
                summary="Could not determine merge-base — skipping diff gate",
            )

        stats = _get_diff_stats(project_path, merge_base, head_ref)
        if stats is None:
            return DiffGateResult(
                passed=True,
                files_changed=0,
                insertions=0,
                deletions=0,
                summary="Could not get diff stats — skipping diff gate",
            )

        files_changed, insertions, deletions = stats

        if files_changed == 0:
            return DiffGateResult(
                passed=False,
                files_changed=0,
                insertions=0,
                deletions=0,
                summary="No files changed vs base branch — task has no code changes",
            )

        return DiffGateResult(
            passed=True,
            files_changed=files_changed,
            insertions=insertions,
            deletions=deletions,
            summary=f"{files_changed} files changed, +{insertions}/-{deletions} lines",
        )

    except Exception as e:
        logger.warning("Diff gate check failed, defaulting to pass", error=str(e))
        return DiffGateResult(
            passed=True,
            files_changed=0,
            insertions=0,
            deletions=0,
            summary=f"Diff gate error: {e} — defaulting to pass",
        )


def _get_merge_base(project_path: str, head_ref: str = "HEAD", base_ref: str = "main") -> str | None:
    """Get the merge-base between a head ref and base ref."""
    result = subprocess.run(
        ["git", "merge-base", head_ref, base_ref],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _get_diff_stats(
    project_path: str,
    merge_base: str,
    head_ref: str = "HEAD",
) -> tuple[int, int, int] | None:
    """Get (files_changed, insertions, deletions) from git diff --numstat."""
    result = subprocess.run(
        ["git", "diff", "--numstat", f"{merge_base}..{head_ref}"],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None

    files_changed = 0
    insertions = 0
    deletions = 0

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            files_changed += 1
            # Binary files show "-" for insertions/deletions
            with contextlib.suppress(ValueError):
                insertions += int(parts[0])
            with contextlib.suppress(ValueError):
                deletions += int(parts[1])

    return files_changed, insertions, deletions
