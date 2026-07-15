"""Regression tests for safe cleanup of agent-browser temporary artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REAPER = Path(__file__).resolve().parents[3] / "scripts" / "agent-browser-idle-reaper.js"


def _run_temp_cleanup(temp_root: Path) -> dict[str, list[str]]:
    script = (
        f"const r=require({json.dumps(str(REAPER))});"
        "process.stdout.write(JSON.stringify(r.cleanupTempArtifacts({env:process.env})));"
    )
    env = {
        **os.environ,
        "AGENT_BROWSER_TEMP_ROOT": str(temp_root),
        "AGENT_BROWSER_TEMP_ARTIFACT_RETENTION_MS": "60000",
    }
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(result.stdout)


def test_temp_cleanup_removes_only_old_inactive_known_artifacts(tmp_path: Path) -> None:
    stale_profile = tmp_path / "agent-browser-profile-stale"
    active_profile = tmp_path / "agent-browser-profile-active"
    stale_fetcher = tmp_path / "com.google.Chrome.chrome_chrome_url_fetcher_.stale"
    unrelated = tmp_path / "project-build-cache"
    for candidate in (stale_profile, active_profile, stale_fetcher, unrelated):
        candidate.mkdir()
        old = time.time() - 3600
        os.utime(candidate, (old, old))

    active = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", str(active_profile)]
    )
    try:
        summary = _run_temp_cleanup(tmp_path)
    finally:
        active.terminate()
        active.wait(timeout=5)

    assert not stale_profile.exists()
    assert not stale_fetcher.exists()
    assert active_profile.exists()
    assert unrelated.exists()
    assert sorted(summary["cleaned"]) == sorted([stale_profile.name, stale_fetcher.name])
    assert summary["skippedActive"] == [active_profile.name]


def test_temp_cleanup_keeps_recent_artifact(tmp_path: Path) -> None:
    recent = tmp_path / "agent-browser-profile-recent"
    recent.mkdir()

    summary = _run_temp_cleanup(tmp_path)

    assert recent.exists()
    assert summary["cleaned"] == []
    assert summary["skippedRecent"] == [recent.name]
