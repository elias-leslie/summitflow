"""Codex portability keeps recovery inputs, not its replaceable native runtime."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from app.tasks import backup_native_archive as archive
from app.tasks import backup_native_recovery as recovery


def _write(root: Path, relative: str, value: str = "fixture") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_codex_capture_keeps_only_recovery_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / ".codex"
    included = (
        "config.toml", "AGENTS.md", ".backupignore", "aftertimes-clean.config.toml",
        "agents/custom.toml", "hooks/custom.py", "skills/custom/SKILL.md",
        "skills-disabled/custom/SKILL.md", "session-integrations/codex-session-finalize.sh",
        "generated_images/original.png", "attachments/original.txt",
        "pets/custom/sprite.png", "visualizations/review.html",
    )
    excluded = (
        "auth.json", "sessions/current.jsonl", "archived_sessions/old.jsonl",
        "history.jsonl", "session_index.jsonl", "transcription-history.jsonl",
        "thread_history_1.sqlite", "thread_history_1.sqlite-wal", "state_5.sqlite",
        "future_999.sqlite", "logs_2.sqlite", ".codex-global-state.json",
        ".codex-global-state.json.bak", "memories/generated.md", "cache/file",
        "packages/app-server-daemon/releases/codex", "plugins/cache/plugin/file",
        "shell_snapshots/env.sh", "proxy/ca.pem", "node_modules/library/file",
        "session-integrations/codex-session-sync.log.1", "skills/.system/installed/SKILL.md",
        "hooks/__pycache__/custom.pyc", "skills/custom/.git/objects/object",
    )
    for relative in (*included, *excluded):
        _write(project, relative, "{}" if relative == ".codex-global-state.json" else "fixture")

    def unwanted(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Codex essentials must not read native Git or database credentials")

    monkeypatch.setattr(recovery, "git_state", unwanted)
    monkeypatch.setattr(archive, "_dump_database", unwanted)
    payload = archive.prepare_project_payload(project, ".codex", tmp_path / "staging", {})
    snapshot = payload["snapshot_dir"]
    assert all((snapshot / relative).is_file() for relative in included)
    assert all(not (snapshot / relative).exists() for relative in excluded)
    manifest = json.loads((snapshot / ".summitflow-recovery/manifest.json").read_text())
    assert manifest["capture_profile"] == "codex-restore-essentials-v1"
    assert manifest["git"] is None
    assert payload["expects_db"] is False
    assert payload["verification"]["recovery"] == manifest


def test_codex_tracked_runtime_cannot_reenter_through_git_bundle(tmp_path: Path) -> None:
    project = tmp_path / ".codex"
    _write(project, "AGENTS.md")
    _write(project, "packages/runtime/private-history.txt")
    for args in (("init", "-q"), ("add", "."), ("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost.invalid", "commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)
    payload = archive.prepare_project_payload(project, ".codex", tmp_path / "staging", {})
    snapshot = payload["snapshot_dir"]
    assert not (snapshot / "packages").exists()
    assert not (snapshot / ".summitflow-recovery/git.bundle").exists()
    assert not (snapshot / ".summitflow-recovery/git-index").exists()
    assert payload["recovery"]["git"] is None


def test_codex_excluded_runtime_churn_does_not_invalidate_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / ".codex"
    _write(project, "AGENTS.md")
    _write(project, ".codex-global-state.json", "{}")
    original = recovery.copy_inventory_snapshot

    def copy_then_change(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        _write(project, ".codex-global-state.json", "{unfinished")
        _write(project, "sessions/another.jsonl")

    monkeypatch.setattr(recovery, "copy_inventory_snapshot", copy_then_change)
    payload = archive.prepare_project_payload(project, ".codex", tmp_path / "staging", {})
    assert payload["recovery"]["consistent"] is True
    assert not (payload["snapshot_dir"] / ".codex-global-state.json").exists()


def test_codex_configuration_links_remain_mapped_not_followed(tmp_path: Path) -> None:
    project = tmp_path / ".codex"
    project.mkdir()
    canonical = tmp_path / "codex-config"
    _write(canonical, "config.toml")
    (project / "config.toml").symlink_to(canonical / "config.toml")
    payload = archive.prepare_project_payload(project, ".codex", tmp_path / "staging", {}, source_roots={"codex-config": canonical})
    assert payload["recovery"]["mapped_links"] == [{"path": "config.toml", "target_source": "codex-config", "target_relative_path": "config.toml"}]
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    restored = isolated / ".codex"
    payload["snapshot_dir"].rename(restored)
    destination = isolated / "codex-config"
    _write(destination, "config.toml")
    assert recovery.restore_mapped_links(restored, destination_roots={"codex-config": destination}, isolated_root=isolated)["mapped_links_restored"] == 1
    assert (restored / "config.toml").read_text() == "fixture"


@pytest.mark.parametrize("name", ["ordinary-project", "codex-config"])
def test_other_sources_keep_full_git_and_native_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    project = tmp_path / name
    _write(project, "state.sqlite", "ordinary durable file")
    _write(project, "sessions/history.jsonl", '{"important":true}\n')
    for args in (("init", "-q"), ("add", "."), ("-c", "user.name=Fixture", "-c", "user.email=fixture@localhost.invalid", "commit", "-qm", "fixture")):
        subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True)
    monkeypatch.setattr(archive, "_dump_database", lambda *_args: (0, False))
    payload = archive.prepare_project_payload(project, name, tmp_path / "staging", {})
    assert (payload["snapshot_dir"] / "state.sqlite").is_file()
    assert (payload["snapshot_dir"] / "sessions/history.jsonl").is_file()
    assert (payload["snapshot_dir"] / ".summitflow-recovery/git.bundle").is_file()
    assert payload["recovery"]["git"]["head"]
    assert "capture_profile" not in payload["recovery"]
