from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.tasks._retention_check_artifacts import prune_check_artifacts

NOW = datetime(2026, 10, 12, tzinfo=UTC)
LIMITS = {"details_max_age_hours": 7 * 24, "stages_max_age_hours": 14 * 24,
          "observations_max_age_hours": 3 * 24, "observations_keep": 2}


def _aged(path: Path, days: float, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content)
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def test_prunes_only_old_unreferenced_check_evidence(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    tools, st = tmp_path / ".dev-tools", tmp_path / ".git" / "st"
    old_detail = _aged(tools / "ruff-18dde0714e6961ef-941569-e3395c60-details.txt", 10)
    aliased = _aged(tools / "types-18dde0714e6961ef-941569-e3395c61-details.txt", 10)
    (tools / "types-details.txt").symlink_to(aliased.name)
    fresh_detail = _aged(tools / "pytest-0cccb31fb2e045b3bcc5a6dec46d6dbc-details.xml", 1)
    keepsake = _aged(tools / "release-prep" / "notes.txt", 60)
    referenced, orphan = "a" * 64, "b" * 64
    _aged(st / "acceptance" / "receipt.json", 30, f'{{"sha256": "{referenced}"}}')
    stale_cache = _aged(st / "native-stages" / f"{'c' * 64}-python.json", 20, f'{{"sha256": "{orphan}"}}')
    kept_artifact = _aged(st / "native-stages" / "artifacts" / referenced, 20)
    old_artifact = _aged(st / "native-stages" / "artifacts" / orphan, 20)
    observations = st / "acceptance" / "isolated-observations"
    runs = [_aged(observations / name / "log.txt", days).parent for name, days in
            (("newest", 0.1), ("recent", 0.2), ("third", 0.3), ("old", 5))]
    for run, days in zip(runs, (0.1, 0.2, 0.3, 5), strict=True):
        _aged(run, days)
    old_log = _aged(observations / "old.log", 5)

    result = prune_check_artifacts(tmp_path, now=NOW, **LIMITS)

    gone = {old_detail, stale_cache, old_artifact, runs[2], runs[3], old_log}
    assert {Path(path) for path in result["deleted"]} == gone
    for path in (aliased, fresh_detail, keepsake, kept_artifact, runs[0], runs[1], st / "acceptance" / "receipt.json"):
        assert path.exists()


def test_project_without_git_state_only_prunes_details(tmp_path: Path) -> None:
    detail = _aged(tmp_path / ".dev-tools" / "biome-18dde0714e6961ef-1-e3395c60-details.txt", 30)
    assert prune_check_artifacts(tmp_path, now=NOW, **LIMITS)["deleted"] == [str(detail)]
