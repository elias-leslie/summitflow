"""Measured cost decides which admission class a check or cleanroom run takes.

Cheap work must not queue behind a closed heavy gate (Nightshift amber, a held
lane). A run joins the light class only when the last run of the same scope
(per project, ``.git/st/lane-measurements.json``) was both fast and small;
anything unmeasured, slow or large stays heavy, so real memory protection is
unchanged. Limits are data: the defaults below, overridable per project in
``.st-check.toml``::

    [lanes.types]
    max_execution_ms = 2000   # last run at most this long ...
    max_rss_kb = 1048576      # ... and at most this big joins the light class
    class = "heavy"           # or "light": pins the class and skips measurement
"""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# Name -> (max execution ms, max peak child RSS KiB). A vitest suite that took
# seconds and little memory (aico: 470 tests, 6.7 s, 164 MB) joins the light
# lane; so do type checks and tiny cleanroom fixtures, which waited minutes
# behind a closed gate for under a second of work.
DEFAULT_LIMITS: dict[str, tuple[float, int]] = {
    "vitest": (30_000.0, 1024 * 1024),
    "types": (2_000.0, 1024 * 1024),
    "tsc": (2_000.0, 1024 * 1024),
    "cleanroom": (5_000.0, 512 * 1024),
}
_SCOPED = frozenset({"types", "tsc"})
_KEPT_CLEANROOM_KEYS = 50


def scope_keys(name: str, extra_args: Sequence[str] = ()) -> list[str]:
    """Measurement keys for a run, most specific first; [] when nothing applies.

    A type check is scoped by how many paths it takes. A faster whole-project
    run also bounds any subset of the same project, so it covers file scopes
    that have not been timed yet (changed-only runs pass several paths).
    """
    if name not in _SCOPED:
        return [name]
    paths = sum(1 for arg in extra_args if arg and not arg.startswith("-"))
    if paths == 0:
        return [f"{name}:project"]
    return [f"{name}:{'file' if paths == 1 else 'files'}", f"{name}:project"]


def cleanroom_keys(command: Sequence[str], *, deps: bool = False, clone: str | None = None) -> list[str]:
    digest = hashlib.sha256(json.dumps([list(command), deps, clone]).encode()).hexdigest()[:16]
    return [f"cleanroom:{digest}"]


def _store(root: Path) -> Path | None:
    state = root / ".git" / "st"
    return state / "lane-measurements.json" if state.is_dir() else None


def _lane_config(root: Path, name: str) -> dict[str, Any]:
    try:
        lanes = tomllib.loads((root / ".st-check.toml").read_text(encoding="utf-8")).get("lanes")
        entry = lanes.get(name) if isinstance(lanes, dict) else None
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return entry if isinstance(entry, dict) else {}


def _limits(root: Path, name: str) -> tuple[float, int] | None:
    configured = _lane_config(root, name)
    default = DEFAULT_LIMITS.get(name)
    try:
        if default is None and not {"max_execution_ms", "max_rss_kb"} <= configured.keys():
            return None
        base = default or (0.0, 0)
        return float(configured.get("max_execution_ms", base[0])), int(configured.get("max_rss_kb", base[1]))
    except (TypeError, ValueError):
        return default


def pinned_class(root: Path, name: str) -> str | None:
    value = _lane_config(root, name).get("class")
    return value if value in {"light", "heavy"} else None


def admission_class(root: Path, name: str, keys: Sequence[str]) -> str:
    """"light" when the pinned or last measured run of this scope was cheap, else "heavy"."""
    if (pinned := pinned_class(root, name)) is not None:
        return pinned
    limits, path = _limits(root, name), _store(root)
    if limits is None or path is None or not keys:
        return "heavy"
    try:
        values = json.loads(path.read_text())
        key = next((key for key in keys if isinstance(values.get(key), dict)), None)
        last = values[key] if key else {}
        return "light" if float(last["execution_ms"]) <= limits[0] and int(last["max_rss_kb"]) <= limits[1] else "heavy"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "heavy"


def record(root: Path, name: str, keys: Sequence[str], execution_ms: float, max_rss_kb: int) -> None:
    """Keep this run's cost under its own (first) scope; other scopes stay as they were."""
    path = _store(root)
    if path is None or not keys or pinned_class(root, name) is not None or _limits(root, name) is None:
        return
    try:
        values = json.loads(path.read_text()) if path.is_file() else {}
        values = values if isinstance(values, dict) else {}
        values.pop(keys[0], None)
        values[keys[0]] = {"execution_ms": round(execution_ms, 3), "max_rss_kb": max_rss_kb}
        stale = [key for key in values if key.startswith("cleanroom:")][:-_KEPT_CLEANROOM_KEYS]
        for key in stale:
            del values[key]
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(values))
        os.replace(temporary, path)
    except (OSError, ValueError):
        return
