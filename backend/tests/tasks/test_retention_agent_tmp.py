"""Agent temp aging: stale owner units go, fresh or held ones stay; settings override the policy."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.tasks import _retention_agent_tmp as agent_tmp
from app.utils import host_retention_policy as hrp


def _unit(path: Path, age_hours: float) -> Path:
    path.mkdir(parents=True)
    (path / "f").write_text("x" * 100)
    return path


def test_stale_units_go_fresh_and_unmatched_stay(tmp_path: Path, mocker) -> None:
    mocker.patch.object(agent_tmp, "mount_skip_reason", lambda path, mountinfo: None)
    now = datetime.now(UTC)
    old_session = _unit(tmp_path / "claude-1000" / "proj" / "sess-old", 100)
    new_session = _unit(tmp_path / "claude-1000" / "proj" / "sess-new", 1)
    build = _unit(tmp_path / "go-build123", 60)
    other = _unit(tmp_path / "keep-me", 500)
    ages = {old_session: 100, new_session: 1, build: 60, other: 500}
    real = agent_tmp._tree_stats

    def stats(path: Path, *, max_entries: int):
        found = real(path, max_entries=max_entries)
        assert found is not None
        newest, size, count = found
        hours = next((h for p, h in ages.items() if path == p), None)
        return ((now - timedelta(hours=hours)).timestamp() if hours is not None else newest, size, count)

    mocker.patch.object(agent_tmp, "_tree_stats", stats)
    result = agent_tmp.age_agent_tmp(agent_max_age_hours=72, build_max_age_hours=48, now=now, root=tmp_path,
                                     proc_root=tmp_path / "no-proc")
    assert sorted(result["deleted_paths"]) == sorted([str(old_session), str(build)])
    assert new_session.exists() and other.exists() and not old_session.exists() and not build.exists()


def test_pressure_stops_once_relieved_and_dry_run_keeps(tmp_path: Path, mocker) -> None:
    mocker.patch.object(agent_tmp, "mount_skip_reason", lambda path, mountinfo: None)
    now = datetime.now(UTC) + timedelta(days=30)
    a = _unit(tmp_path / "go-build-a", 0)
    result = agent_tmp.age_agent_tmp(agent_max_age_hours=72, build_max_age_hours=48, now=now, root=tmp_path,
                                     dry_run=True, proc_root=tmp_path / "no-proc")
    assert result["deleted_paths"] == [str(a)] and a.exists()
    result = agent_tmp.age_agent_tmp(agent_max_age_hours=72, build_max_age_hours=48, now=now, root=tmp_path,
                                     pressured=lambda: False, proc_root=tmp_path / "no-proc")
    assert result["deleted_paths"] == [] and a.exists()


def test_settings_override_env_and_validate(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "host-retention.json"
    monkeypatch.setattr(hrp, "SETTINGS_PATH", path)
    monkeypatch.setenv("SF_HOST_RETENTION_AGENT_TMP_MAX_AGE_HOURS", "96")
    assert hrp.HostRetentionPolicy.from_env().agent_tmp_max_age_hours == 96
    hrp.write_settings({"agent_tmp_max_age_hours": 24, "go_cache_max_gb": 8})
    policy = hrp.HostRetentionPolicy.from_env()
    assert (policy.agent_tmp_max_age_hours, policy.go_cache_max_gb) == (24, 8.0)
    assert policy.defaults_for()["agent_tmp_max_age_hours"] == 96
    hrp.write_settings({"agent_tmp_max_age_hours": None})
    assert hrp.HostRetentionPolicy.from_env().agent_tmp_max_age_hours == 96
    with pytest.raises(ValueError, match="from 6 to 720"):
        hrp.write_settings({"agent_tmp_max_age_hours": 1})
    with pytest.raises(ValueError, match="can't be changed here"):
        hrp.write_settings({"pressure_min_free_gb": 1})
    assert os.path.exists(path)
