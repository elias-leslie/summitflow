from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.commands import cleanup
from cli.lib import cleanroom_prune

DAY = 86400.0


def _job(parent: Path, name: str, *, age: float, size: int = 10) -> Path:
    job = parent / name
    (job / "repo").mkdir(parents=True)
    (job / "repo" / "file").write_bytes(b"x" * size)
    stamp = time.time() - age
    for path in (job / "repo" / "file", job / "repo", job):
        os.utime(path, (stamp, stamp))
    return job


@pytest.fixture
def parent(tmp_path: Path) -> Path:
    directory = tmp_path / "st-cleanrooms"
    directory.mkdir(mode=0o700)
    return directory


def test_matches_only_cleanroom_pattern_and_age(parent: Path) -> None:
    old = _job(parent, "aico-cleanroom-shq2mgj4", age=2 * DAY)
    _job(parent, "neri-cleanroom-a155uipy", age=60)
    _job(parent, "aico-not-a-cleanroom", age=2 * DAY)
    _job(parent, "aico-cleanroom-TOOLONGSUFFIX", age=2 * DAY)
    (parent / "stray-cleanroom-abcdefgh").write_text("file, not dir")
    jobs = cleanroom_prune.find_cleanroom_jobs(parent, older_than=DAY, cwds=())
    assert [job.path for job in jobs] == [old]
    assert jobs[0].project == "aico"
    assert jobs[0].size_bytes > 0


def test_project_filter_handles_hyphenated_names(parent: Path) -> None:
    _job(parent, "aico-cleanroom-shq2mgj4", age=2 * DAY)
    portfolio_ai = _job(parent, "portfolio-ai-cleanroom-2ws3p9w8", age=2 * DAY)
    jobs = cleanroom_prune.find_cleanroom_jobs(parent, older_than=0, project="portfolio-ai", cwds=())
    assert [job.path for job in jobs] == [portfolio_ai]


def test_symlinked_job_is_refused_and_target_untouched(parent: Path, tmp_path: Path) -> None:
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep").write_text("data")
    link = parent / "aico-cleanroom-abcdefgh"
    link.symlink_to(target, target_is_directory=True)
    (job,) = cleanroom_prune.find_cleanroom_jobs(parent, older_than=0, cwds=())
    assert job.skip_reason == "symlink refused"
    with pytest.raises(ValueError, match="symlink"):
        cleanroom_prune.remove_job(job)
    assert (target / "keep").read_text() == "data"


def test_inner_symlinks_are_not_followed_on_removal(parent: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("data")
    job_path = _job(parent, "aico-cleanroom-abcdefgh", age=2 * DAY)
    (job_path / "repo" / "link").symlink_to(outside, target_is_directory=True)
    (job,) = cleanroom_prune.find_cleanroom_jobs(parent, older_than=0, cwds=())
    cleanroom_prune.remove_job(job)
    assert not job_path.exists()
    assert (outside / "keep").read_text() == "data"


def test_live_process_cwd_is_skipped(parent: Path) -> None:
    busy = _job(parent, "aico-cleanroom-busy0000", age=2 * DAY)
    idle = _job(parent, "aico-cleanroom-idle0000", age=2 * DAY)
    jobs = cleanroom_prune.find_cleanroom_jobs(parent, older_than=DAY, cwds={busy / "repo"})
    reasons = {job.path: job.skip_reason for job in jobs}
    assert reasons == {busy: "in use by a live process", idle: None}


def test_live_cwds_reads_proc_links(tmp_path: Path) -> None:
    proc = tmp_path / "proc"
    (proc / "123").mkdir(parents=True)
    (proc / "123" / "cwd").symlink_to("/srv/scratch/x-cleanroom-abcdefgh/repo")
    (proc / "self").mkdir()
    (proc / "456").mkdir()
    assert cleanroom_prune.live_cwds(proc) == {Path("/srv/scratch/x-cleanroom-abcdefgh/repo")}


@pytest.mark.parametrize(("raw", "seconds"), [("24h", DAY), ("30m", 1800), ("2d", 2 * DAY), ("0", 0), ("90s", 90)])
def test_parse_age(raw: str, seconds: float) -> None:
    assert cleanroom_prune.parse_age(raw) == seconds


def test_parse_age_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        cleanroom_prune.parse_age("yesterday")


def test_command_dry_run_then_delete_reports_freed_bytes(
    parent: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _job(parent, "aico-cleanroom-shq2mgj4", age=2 * DAY, size=8192)
    fresh = _job(parent, "aico-cleanroom-fresh000", age=60)
    monkeypatch.setattr(cleanroom_prune, "cleanroom_parent", lambda: parent)
    monkeypatch.setattr(cleanroom_prune, "live_cwds", lambda: set())
    runner = CliRunner()

    dry = runner.invoke(cleanup.app, ["cleanrooms", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    assert "Would remove aico-cleanroom-shq2mgj4" in dry.output
    assert "Would remove 1 cleanroom(s), would free" in dry.output
    assert old.exists()

    real = runner.invoke(cleanup.app, ["cleanrooms", "--older-than", "1d", "--project", "aico"])
    assert real.exit_code == 0, real.output
    assert "Removed 1 cleanroom(s), freed" in real.output
    assert not old.exists()
    assert fresh.exists()


def test_command_rejects_bad_duration() -> None:
    result = CliRunner().invoke(cleanup.app, ["cleanrooms", "--older-than", "soon"])
    assert result.exit_code == 2
