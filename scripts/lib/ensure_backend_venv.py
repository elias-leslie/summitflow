"""Ensure the script runs inside the backend virtualenv.

Import this module at the top of any repo utility script that depends on
backend packages.  It will:

1. Locate the backend ``.venv`` relative to the repository root.
2. If the current interpreter is *not* the venv Python, ``os.execv`` into
   the correct one (re-launching the same script with the same arguments).
3. Prepend the backend directory to ``sys.path`` so that
   ``from app.…`` imports work.

Usage (must appear before any ``from app…`` import)::

    # At the very top of your script, after ``from __future__`` imports:
    sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "scripts"))
    import lib.ensure_backend_venv  # noqa: E402, F401

If the script lives outside the repo root (unlikely), the module is a no-op.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _repo_root() -> Path | None:
    """Walk up from this file to find the repository root (contains 'backend/')."""
    candidate = Path(__file__).resolve().parents[2]  # scripts/lib/… -> repo root
    if (candidate / "backend").is_dir():
        return candidate
    return None


def _find_venv_python(root: Path) -> Path | None:
    """Return the venv Python path for a repo root, or None."""
    venv_python = root / "backend" / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else None


def _venv_root(executable: str | Path) -> Path | None:
    """Return the virtualenv root for a Python shim path, if recognizable."""
    path = Path(executable).expanduser()
    if path.parent.name != "bin":
        return None
    return path.parent.parent


def _same_venv(current_executable: str | Path, target_executable: Path) -> bool:
    """Return True when both interpreter paths belong to the same virtualenv."""
    current_path = Path(current_executable).expanduser()
    target_path = target_executable.expanduser()
    if current_path == target_path:
        return True

    current_root = _venv_root(current_path)
    target_root = _venv_root(target_path)
    if current_root is None or target_root is None:
        return False
    return current_root == target_root


def _activate() -> None:
    root = _repo_root()
    if root is None:
        return

    backend_root = root / "backend"

    # Look for the venv in the current checkout.
    venv_python = _find_venv_python(root)

    # Re-exec into the venv interpreter if we are running under a different one.
    if venv_python is not None and not _same_venv(sys.executable, venv_python):
        os.execv(str(venv_python), [str(venv_python), *sys.argv])

    # Make ``from app.…`` imports work.
    backend_str = str(backend_root)
    if backend_str not in sys.path:
        sys.path.insert(0, backend_str)


_activate()
