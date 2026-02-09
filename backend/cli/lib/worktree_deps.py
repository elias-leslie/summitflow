"""Dependency symlinking for worktrees."""

from __future__ import annotations

import subprocess
from pathlib import Path


def discover_dep_dirs(repo_root: Path, max_depth: int = 3) -> list[tuple[str, str]]:
    """Discover gitignored dependency directories (.venv, node_modules) in repo.

    Walks up to max_depth levels deep, skips inside dep dirs themselves.
    Returns (relative_path, parent_relative_path) pairs.
    """
    dep_names = {"node_modules"}
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
            if entry.name in dep_names:
                rel = entry.relative_to(repo_root)
                result = subprocess.run(
                    ["git", "check-ignore", "-q", str(rel)],
                    cwd=repo_root,
                    capture_output=True,
                )
                if result.returncode == 0:
                    parent_rel = str(rel.parent) if len(rel.parts) > 1 else "."
                    pairs.append((str(rel), parent_rel))
                    found.add(entry)
            elif entry not in found:
                _walk(entry, depth + 1)

    _walk(repo_root, 1)
    return pairs


def symlink_gitignored_deps(repo_root: Path, worktree_path: Path) -> None:
    """Symlink gitignored dependency directories from main repo into worktree.

    git worktree add doesn't include gitignored dirs (node_modules, .venv).
    Without these, tools like `dt --check` fail when they detect frontend/
    exists but node_modules/ is missing.
    """
    symlink_pairs = discover_dep_dirs(repo_root)
    created_symlinks: list[str] = []
    for dep_rel, parent_rel in symlink_pairs:
        main_dep = repo_root / dep_rel
        wt_parent = worktree_path / parent_rel if parent_rel != "." else worktree_path
        if main_dep.exists() and wt_parent.exists():
            wt_dep = worktree_path / dep_rel
            if not wt_dep.exists():
                wt_dep.symlink_to(main_dep)
                created_symlinks.append(dep_rel)

    if created_symlinks:
        git_dir = worktree_path / ".git"
        if git_dir.is_file():
            real_git = Path(git_dir.read_text().strip().removeprefix("gitdir: "))
            exclude_file = real_git / "info" / "exclude"
        else:
            exclude_file = git_dir / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_file.read_text() if exclude_file.exists() else ""
        with open(exclude_file, "a") as f:
            for dep in created_symlinks:
                if dep not in existing:
                    f.write(f"{dep}\n")
