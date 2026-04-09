"""Helpers for reading env-file keys and scrubbing inherited variables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path


def _iter_env_keys(path: Path) -> Iterable[str]:
    if not path.exists():
        return ()

    keys: list[str] = []
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key = raw_line.split("=", 1)[0].strip()
        if key:
            keys.append(key)
    return keys


def scrub_env_keys_from_files(
    env: Mapping[str, str],
    paths: Iterable[Path],
    *,
    extra_keys: Iterable[str] = (),
) -> dict[str, str]:
    """Return a copy of env without keys declared by the given env files."""
    scrubbed = dict(env)
    for path in paths:
        for key in _iter_env_keys(path):
            scrubbed.pop(key, None)
    for key in extra_keys:
        scrubbed.pop(key, None)
    return scrubbed


def project_env_files(project_root: Path) -> list[Path]:
    """Return the canonical env files for a project root."""
    return [
        project_root / ".env",
        project_root / ".env.local",
        project_root / ".env.example",
    ]
