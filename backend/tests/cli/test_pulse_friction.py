"""The st pulse friction line and informal-worktree audit read their canonical sources only."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cli.commands import pulse_friction


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    _git(path, "config", "core.hooksPath", "/dev/null")
    (path / "a.txt").write_text("a\n")
    _git(path, "add", "a.txt")
    _git(path, "commit", "-qm", "one")
    return path


def _receipt(repo: Path, sha: str, status: str, observed: str, project: str = "proj") -> None:
    directory = repo / ".git" / "st" / "publication"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{sha}.json").write_text(json.dumps(
        {"project_id": project, "source_commit": sha, "observed_at": observed, "observation": {"status": status}}))


def test_unpublished_counts_commits_since_last_published_receipt(repo: Path) -> None:
    published = _git(repo, "rev-parse", "HEAD")
    _receipt(repo, published, "published", "2026-10-16T10:00:00+00:00")
    for name in ("b", "c"):
        (repo / name).write_text(name)
        _git(repo, "add", name)
        _git(repo, "commit", "-qm", name)
    # A newer pending attempt and another project's receipt do not move the basis.
    _receipt(repo, _git(repo, "rev-parse", "HEAD"), "pending", "2026-10-16T12:00:00+00:00")
    _receipt(repo, "f" * 40, "published", "2026-10-16T13:00:00+00:00", project="other")

    assert pulse_friction.unpublished(repo, "proj") == "unpublished[proj]=2commits/oldest_0h"


def test_unpublished_without_receipt(repo: Path) -> None:
    assert pulse_friction.unpublished(repo, "proj") == "unpublished[proj]=no-receipt"


def test_sweep_refusals_count_only_the_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.lib import leases

    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path)
    now = datetime.now(UTC)
    rows = [{"at": now.isoformat()}, {"at": (now - timedelta(days=8)).isoformat()}, {"bad": 1}]
    (tmp_path / "_sweep_refusals.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")

    assert pulse_friction._sweep_refusals() == "sweep_refusals=1"


def test_rebuilds_read_recent_job_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path))
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for index, state in enumerate(("succeeded", "succeeded", "failed", "running")):
        (jobs / f"{index:032x}.json").write_text(json.dumps({"state": state}))
    old = jobs / f"{9:032x}.json"
    old.write_text(json.dumps({"state": "failed"}))
    stale = time.time() - 8 * 86400
    os.utime(old, (stale, stale))
    (jobs / f"{1:032x}.deployment.json").write_text(json.dumps({"state": "failed"}))

    assert pulse_friction._rebuilds() == "rebuilds=2ok/1failed"


def test_friction_line_degrades_per_metric(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    def broken() -> str:
        raise OSError("agent hub down")

    monkeypatch.setattr(pulse_friction, "_session_metrics", broken)
    monkeypatch.setattr(pulse_friction, "_sweep_refusals", lambda: "sweep_refusals=0")
    monkeypatch.setattr(pulse_friction, "_rebuilds", lambda: "rebuilds=1ok/0failed")
    monkeypatch.setattr(pulse_friction, "_handshakes", lambda: "handshakes_24h=3")

    line = pulse_friction.friction_line([("proj", repo)])

    assert line == ("FRICTION[host,7d]:commits=unavailable|sweep_refusals=0|rebuilds=1ok/0failed"
                    "|handshakes_24h=3|unpublished[proj]=no-receipt")


def test_worktree_lines_flag_dirty_worktree_outside_workspace(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(repo))
    outside = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", "--detach", str(outside))
    (outside / "a.txt").write_text("changed\n")

    lines = pulse_friction.worktree_lines(repo)

    assert lines == [f"WORKTREE:repo|{outside}|branch=detached|dirty=1|unlanded=0|outside_workspace"
                     "|action=land-or-hand-off-then-git-worktree-remove"]


def test_worktree_lines_silent_for_clean_worktree_inside_workspace(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    _git(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "wt"))

    assert pulse_friction.worktree_lines(repo) == []


def test_pulse_compact_prints_worktree_and_friction_lines(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    from cli.commands import pulse as pulse_cmd

    seen: list[object] = []
    monkeypatch.setattr(pulse_friction, "worktree_lines", lambda path: [f"WORKTREE:{path.name}|x"])
    monkeypatch.setattr(pulse_friction, "friction_line", lambda repos=(): seen.append(list(repos)) or "FRICTION[x]")
    payload = {"project_id": "proj", "summary": {}, "cleanup": {"path": str(repo)}}
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *args, **_: printed.append(" ".join(map(str, args))))

    pulse_cmd._print_compact([payload])
    pulse_cmd._print_compact([payload, {**payload, "project_id": "two"}])

    assert "WORKTREE:repo|x" in printed
    assert printed.count("FRICTION[x]") == 2
    # Publication lag only for a single-project pulse.
    assert seen == [[("proj", repo)], []]
