"""Age out regenerable `st check` evidence in each managed project.

- ``.dev-tools`` per-invocation detail files (the latest alias targets stay).
- Native stage reuse caches, and retained native artifacts no remaining cache
  or acceptance receipt names by digest; receipts themselves are kept.
- Isolated acceptance observations (copies kept to diagnose a failed or
  interrupted run): past the age limit, or beyond the newest ``keep``.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from ._retention_fs import CleanupResult, age_hours, delete_path

DETAIL_FILE = re.compile(r"[a-z0-9-]+-[0-9a-f]{12,20}-\d+-[0-9a-f]{8}-details\.(?:txt|xml)|pytest-[0-9a-f]{32}-details\.xml")
DIGEST = re.compile(rb"[0-9a-f]{64}")


def _common_dir(root: Path) -> Path | None:
    result = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=root, capture_output=True, text=True, check=False)
    return Path(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else None


def _referenced_digests(files: Iterable[Path]) -> set[bytes]:
    found: set[bytes] = set()
    for path in files:
        try:
            found.update(DIGEST.findall(path.read_bytes()))
        except OSError:
            continue
    return found


def prune_check_artifacts(
    root: Path, *, now: datetime, details_max_age_hours: int, stages_max_age_hours: int,
    observations_max_age_hours: int, observations_keep: int,
) -> CleanupResult:
    deleted: list[str] = []
    reclaimed = 0

    def remove(path: Path) -> None:
        nonlocal reclaimed
        reclaimed += delete_path(path)
        deleted.append(str(path))

    details = root / ".dev-tools"
    if details.is_dir():
        aliased = {link.readlink().name for link in details.iterdir() if link.is_symlink()}
        for path in details.iterdir():
            if (DETAIL_FILE.fullmatch(path.name) and path.name not in aliased and not path.is_symlink()
                    and path.is_file() and age_hours(path, now=now) >= details_max_age_hours):
                remove(path)

    common = _common_dir(root)
    if common is None:
        return CleanupResult(deleted_paths=len(deleted), bytes_reclaimed=reclaimed, deleted=deleted)
    stages = common / "st" / "native-stages"
    acceptance = common / "st" / "acceptance"
    if stages.is_dir():
        caches = sorted(stages.glob("*.json"))
        for path in caches:
            if age_hours(path, now=now) >= stages_max_age_hours:
                remove(path)
        artifacts = stages / "artifacts"
        if artifacts.is_dir():
            live = _referenced_digests([*stages.glob("*.json"), *acceptance.glob("*.json")])
            for path in artifacts.iterdir():
                if path.name.encode() not in live and age_hours(path, now=now) >= stages_max_age_hours:
                    remove(path)

    observations = acceptance / "isolated-observations"
    if observations.is_dir():
        runs = sorted((path for path in observations.iterdir() if path.is_dir() and not path.is_symlink()),
                      key=lambda path: path.stat().st_mtime, reverse=True)
        for index, run in enumerate(runs):
            if index >= observations_keep or age_hours(run, now=now) >= observations_max_age_hours:
                remove(run)
                log = run.with_name(run.name + ".log")
                if log.is_file():
                    remove(log)
    return CleanupResult(deleted_paths=len(deleted), bytes_reclaimed=reclaimed, deleted=deleted)
