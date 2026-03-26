"""Safe repo-local path cleanup for the st CLI."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import typer

from ..config import get_config_optional
from ..output import output_error, output_json
from .cleanup_git import get_repo_root

_PROTECTED_NAMES = frozenset({".git", ".st", "node_modules"})
_FORBIDDEN_ROOTS = frozenset({
    "/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64",
    "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys", "/tmp",
    "/usr", "/var",
})
_GLOB_CHARS = frozenset({"*", "?"})


@dataclass(frozen=True)
class CleanupTarget:
    """Validated cleanup target inside the active repository."""

    raw_path: str
    absolute_path: Path
    relative_path: str
    path_type: str


def _get_project_root() -> Path:
    """Resolve the active git/worktree root, falling back to configured project root."""
    repo_root = get_repo_root()
    if repo_root is None:
        config = get_config_optional()
        if config.project_root:
            return Path(config.project_root).resolve()
        output_error("Could not determine repository root. Run from inside a git repo or registered project.")
        raise typer.Exit(1)
    return repo_root.resolve()


def _looks_like_glob(raw_path: str) -> bool:
    """Return True if the user passed glob-like characters (``*`` or ``?``).

    Brackets are intentionally excluded because Next.js uses ``[param]``
    route segments that are valid literal path components.
    """
    return any(char in raw_path for char in _GLOB_CHARS)


def _count_entries(path: Path) -> int:
    """Count files and directories under a path, including the path itself."""
    if not path.exists() and not path.is_symlink():
        return 0
    if path.is_file() or path.is_symlink():
        return 1
    return 1 + sum(1 for _ in path.rglob("*"))


def _validate_non_repo_path(target: Path, raw_path: str, recursive: bool) -> CleanupTarget:
    """Validate a path outside any git repo against safety checks."""
    home = Path.home().resolve()

    if target == home or target == home.parent:
        output_error(f"Refusing to cleanup home directory or its parent: {raw_path}")
        raise typer.Exit(1)

    target_str = str(target)
    if target_str in _FORBIDDEN_ROOTS or any(target_str == r for r in _FORBIDDEN_ROOTS):
        output_error(f"Refusing to cleanup system directory: {raw_path}")
        raise typer.Exit(1)

    if not target_str.startswith(str(home)):
        output_error(f"Refusing to cleanup path outside home directory: {raw_path}")
        raise typer.Exit(1)

    if not target.exists() and not target.is_symlink():
        output_error(f"Path does not exist: {raw_path}")
        raise typer.Exit(1)

    if target.is_dir() and not recursive:
        output_error(f"Directory cleanup requires --recursive: {raw_path}")
        raise typer.Exit(1)

    path_type = "directory" if target.is_dir() else "file"
    relative_str = str(target.relative_to(home))
    return CleanupTarget(
        raw_path=raw_path,
        absolute_path=target,
        relative_path=relative_str,
        path_type=path_type,
    )


def validate_cleanup_target(raw_path: str, repo_root: Path, recursive: bool) -> CleanupTarget:
    """Validate a cleanup path before deletion."""
    cleaned = raw_path.strip()
    if not cleaned or cleaned in {".", "./"}:
        output_error("Refusing to cleanup '.' or an empty path. Pass a literal repo-relative path.")
        raise typer.Exit(1)
    if _looks_like_glob(cleaned):
        output_error("Globs are not allowed. Pass one or more literal repo-relative paths.")
        raise typer.Exit(1)

    candidate = Path(cleaned)
    if candidate.is_absolute():
        target = candidate.resolve(strict=False)
    else:
        target = (repo_root / candidate).resolve(strict=False)

    try:
        relative = target.relative_to(repo_root)
    except ValueError:
        # Path is outside the repo — validate as non-repo path
        return _validate_non_repo_path(target, raw_path, recursive)

    if target == repo_root:
        output_error("Refusing to cleanup the repository root.")
        raise typer.Exit(1)

    if any(part in _PROTECTED_NAMES for part in relative.parts):
        output_error(
            f"Refusing to cleanup protected path '{relative}'. Protected directories: {', '.join(sorted(_PROTECTED_NAMES))}."
        )
        raise typer.Exit(1)

    if not target.exists() and not target.is_symlink():
        output_error(f"Path does not exist: {raw_path}")
        raise typer.Exit(1)

    if target.is_dir() and not recursive:
        output_error(f"Directory cleanup requires --recursive: {raw_path}")
        raise typer.Exit(1)

    path_type = "directory" if target.is_dir() else "file"
    return CleanupTarget(
        raw_path=raw_path,
        absolute_path=target,
        relative_path=str(relative),
        path_type=path_type,
    )


def cleanup_path_targets(paths: list[str], recursive: bool, dry_run: bool) -> list[dict[str, object]]:
    """Validate and optionally delete repo-local paths."""
    repo_root = _get_project_root()
    validated = [validate_cleanup_target(path, repo_root, recursive) for path in paths]

    results: list[dict[str, object]] = []
    for target in validated:
        entry_count = _count_entries(target.absolute_path)
        if not dry_run:
            if target.absolute_path.is_dir():
                shutil.rmtree(target.absolute_path)
            else:
                target.absolute_path.unlink()

        results.append(
            {
                "path": target.relative_path,
                "type": target.path_type,
                "entries": entry_count,
                "deleted": not dry_run,
            }
        )

    return results


def cleanup_paths_command(paths: list[str], recursive: bool, dry_run: bool) -> None:
    """Execute safe path cleanup and emit JSON output."""
    results = cleanup_path_targets(paths, recursive=recursive, dry_run=dry_run)
    output_json(
        {
            "dry_run": dry_run,
            "recursive": recursive,
            "targets": results,
            "total_targets": len(results),
            "total_entries": sum(item["entries"] for item in results),
        }
    )
