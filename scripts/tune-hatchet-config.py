#!/usr/bin/env python3
"""Apply conservative runtime tuning to generated Hatchet config files."""

from __future__ import annotations

from pathlib import Path
import sys


REPLACEMENTS = {
    "server.yaml": {
        "schedulerConcurrencyPollingMinInterval": "1000000000",
    },
    "database.yaml": {
        "ddlPoolMaxConns": "2",
        "maxConns": "12",
        "maxQueueConns": "12",
        "minQueueConns": "2",
        "readReplicaMaxConns": "4",
        "readReplicaMinConns": "1",
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _apply_replacements(path: Path, updates: dict[str, str]) -> bool:
    original = path.read_text(encoding="utf-8").splitlines()
    changed = False
    updated_lines: list[str] = []

    for line in original:
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        replaced = False

        for key, value in updates.items():
            if stripped.startswith(f"{key}:"):
                new_line = f"{indent}{key}: {value}"
                updated_lines.append(new_line)
                changed = changed or new_line != line
                replaced = True
                break

        if not replaced:
            updated_lines.append(line)

    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    config_dir = _repo_root() / "docker" / "compose" / "hatchet-config"
    if not config_dir.exists():
        print(f"hatchet config directory not found: {config_dir}", file=sys.stderr)
        return 1

    any_changed = False
    for filename, updates in REPLACEMENTS.items():
        path = config_dir / filename
        if not path.exists():
            print(f"missing config file: {path}", file=sys.stderr)
            return 1
        file_changed = _apply_replacements(path, updates)
        any_changed = any_changed or file_changed
        status = "updated" if file_changed else "unchanged"
        print(f"{filename}: {status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
