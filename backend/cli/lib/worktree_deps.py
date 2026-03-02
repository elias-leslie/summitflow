"""Dependency symlinking for worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path

_DEP_NAMES = {"node_modules"}


def _is_git_ignored(repo_root: Path, rel: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(rel)],
        cwd=repo_root,
        capture_output=True,
    )
    return result.returncode == 0


def discover_dep_dirs(repo_root: Path, max_depth: int = 3) -> list[tuple[str, str]]:
    """Discover gitignored dependency directories (.venv, node_modules) in repo.

    Walks up to max_depth levels deep, skips inside dep dirs themselves.
    Returns (relative_path, parent_relative_path) pairs.
    """
    pairs: list[tuple[str, str]] = []
    found: set[Path] = set()

    def _walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except PermissionError:
            return
        for entry in entries:
            if not entry.is_dir() or entry.name.startswith(".git"):
                continue
            if entry.name not in _DEP_NAMES:
                if entry not in found:
                    _walk(entry, depth + 1)
                continue
            rel = entry.relative_to(repo_root)
            if not _is_git_ignored(repo_root, rel):
                continue
            parent_rel = str(rel.parent) if len(rel.parts) > 1 else "."
            pairs.append((str(rel), parent_rel))
            found.add(entry)

    _walk(repo_root, 1)
    return pairs


def _get_exclude_file(worktree_path: Path) -> Path:
    git_dir = worktree_path / ".git"
    if git_dir.is_file():
        real_git = Path(git_dir.read_text().strip().removeprefix("gitdir: "))
        return real_git / "info" / "exclude"
    return git_dir / "info" / "exclude"


def _maybe_create_symlink(
    repo_root: Path, worktree_path: Path, dep_rel: str, parent_rel: str
) -> str | None:
    main_dep = repo_root / dep_rel
    wt_parent = worktree_path / parent_rel if parent_rel != "." else worktree_path
    if not main_dep.exists() or not wt_parent.exists():
        return None
    wt_dep = worktree_path / dep_rel
    if wt_dep.exists():
        return None
    wt_dep.symlink_to(main_dep)
    return dep_rel


def symlink_gitignored_deps(repo_root: Path, worktree_path: Path) -> None:
    """Symlink gitignored dependency directories from main repo into worktree.

    git worktree add doesn't include gitignored dirs (node_modules, .venv).
    Without these, tools like `dt --check` fail when they detect frontend/
    exists but node_modules/ is missing.
    """
    symlink_pairs = discover_dep_dirs(repo_root)
    created_symlinks = [
        result
        for dep_rel, parent_rel in symlink_pairs
        if (result := _maybe_create_symlink(repo_root, worktree_path, dep_rel, parent_rel))
    ]

    if not created_symlinks:
        return

    exclude_file = _get_exclude_file(worktree_path)
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_file.read_text() if exclude_file.exists() else ""
    with open(exclude_file, "a") as f:
        for dep in created_symlinks:
            if dep not in existing:
                f.write(f"{dep}\n")
