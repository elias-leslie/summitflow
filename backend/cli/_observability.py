"""Best-effort refresh of external agent observability before coordination reads."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_DEFAULT_TIMEOUT_SECONDS = 8.0
_SYNC_DONE = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sync_script() -> Path:
    override = os.environ.get("ST_OBSERVABILITY_SYNC_SCRIPT")
    if override:
        return Path(override).expanduser()
    return _repo_root() / "scripts" / "agent-observability-sync.py"


def _sync_enabled() -> bool:
    raw = os.environ.get("ST_OBSERVABILITY_SYNC", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    # Coordination tests should not shell out to the real host environment.
    return not os.environ.get("PYTEST_CURRENT_TEST")


def _sync_timeout_seconds() -> float:
    raw = os.environ.get("ST_OBSERVABILITY_SYNC_TIMEOUT")
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError:
        return _DEFAULT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else _DEFAULT_TIMEOUT_SECONDS


def refresh_agent_observability() -> None:
    """Refresh external tmux/Codex session state without blocking CLI output on failure."""
    global _SYNC_DONE
    if _SYNC_DONE or not _sync_enabled():
        return
    _SYNC_DONE = True

    script_path = _sync_script()
    if not script_path.is_file():
        return

    try:
        subprocess.run(
            [sys.executable, str(script_path), "--best-effort"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_sync_timeout_seconds(),
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return
