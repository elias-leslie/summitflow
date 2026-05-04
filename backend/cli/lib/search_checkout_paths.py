"""Checkout path and process helpers for `st search`."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SUPPORTED_SYMBOL_EXTENSIONS = {".py", ".ts", ".tsx"}
CHECKOUT_EXCLUDE_GLOBS = (
    "!**/.git/**",
    "!**/node_modules/**",
    "!**/.venv/**",
    "!**/.next/**",
    "!**/dist/**",
    "!**/build/**",
    "!**/coverage/**",
)
CHECKOUT_EXCLUDE_DIRS = {".git", "node_modules", ".venv", ".next", "dist", "build", "coverage", "__pycache__"}
CHECKOUT_RIPGREP_TIMEOUT_SECONDS = 15
CHECKOUT_CANDIDATE_LIMIT = 60
LINE_PREVIEW_LIMIT = 240


def _normalize_path_prefix(path_prefix: str | None) -> str | None:
    """Normalize an optional relative file/subtree prefix."""
    if path_prefix is None:
        return None
    normalized = str(path_prefix).strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/")
    return normalized or None


def _path_matches_prefix(path: str, path_prefix: str | None) -> bool:
    normalized_prefix = _normalize_path_prefix(path_prefix)
    return not normalized_prefix or path == normalized_prefix or path.startswith(f"{normalized_prefix}/")


def _checkout_has_local_changes(root: Path | None) -> bool:
    """Return True when the checkout contains tracked or untracked changes."""
    if root is None:
        return False
    try:
        proc = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return proc.returncode != 0 or bool(proc.stdout.strip())


def _normalize_rel_path(root: Path, path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _resolve_checkout_path_prefix(root: Path, path_prefix: str | None) -> tuple[str | None, Path | None]:
    normalized_prefix = _normalize_path_prefix(path_prefix)
    if not normalized_prefix:
        return None, root
    target = (root / normalized_prefix).resolve()
    rel_target = _normalize_rel_path(root, target)
    if rel_target is None or not target.exists():
        return normalized_prefix, None
    return normalized_prefix, target


def _iter_checkout_files(
    root: Path,
    *,
    allowed_suffixes: set[str] | None = None,
    start_root: Path | None = None,
) -> list[Path]:
    walk_root = (start_root or root).resolve()
    if walk_root.is_file():
        if allowed_suffixes is not None and walk_root.suffix.lower() not in allowed_suffixes:
            return []
        return [walk_root]
    results: list[Path] = []
    for dirpath, dirnames, filenames in walk_root.walk(top_down=True):
        dirnames[:] = [name for name in dirnames if name not in CHECKOUT_EXCLUDE_DIRS]
        for filename in filenames:
            path = dirpath / filename
            if allowed_suffixes is None or path.suffix.lower() in allowed_suffixes:
                results.append(path)
    return results


def _ripgrep_candidate_paths(
    root: Path,
    query: str,
    *,
    limit: int,
    suffixes: set[str] | None = None,
    path_prefix: str | None = None,
) -> list[Path]:
    rg_path = shutil.which("rg")
    if not rg_path:
        return []
    normalized_prefix, target_root = _resolve_checkout_path_prefix(root, path_prefix)
    if normalized_prefix and target_root is None:
        return []

    args = [rg_path, "-l", "--ignore-case", "--fixed-strings", "--hidden"]
    if suffixes:
        for suffix in sorted(suffixes):
            args.extend(["--glob", f"*{suffix}"])
    for glob in CHECKOUT_EXCLUDE_GLOBS:
        args.extend(["--glob", glob])
    args.extend([query, normalized_prefix or "."])

    try:
        proc = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHECKOUT_RIPGREP_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode not in (0, 1):
        return []
    return _existing_file_paths(root, proc.stdout.splitlines(), limit)


def _existing_file_paths(root: Path, lines: list[str], limit: int) -> list[Path]:
    results: list[Path] = []
    for raw_line in lines:
        rel_path = raw_line.strip()
        if not rel_path:
            continue
        candidate = (root / rel_path).resolve()
        if candidate.is_file():
            results.append(candidate)
        if len(results) >= limit:
            break
    return results
