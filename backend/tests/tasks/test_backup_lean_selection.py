"""Approved lean selection must omit output without losing editable recovery inputs."""
from pathlib import Path

import pytest

from app.tasks.backup_native_archive import _load_excludes, _should_exclude


@pytest.mark.parametrize(("source", "path"), [
    ("summitflow", "host-monitor/target/debug/host-monitor"),
    ("summitflow", "backend/logs/summitflow.log.2026-06-06"),
    ("portfolio-ai", "data/backups/portfolio.tar.gz"),
    ("rootfall", "builds/releases-abc/rootfall.zip"),
    ("rootfall", "builds/web/index.wasm"),
    ("cinderwake", "builds/desktop/cinderwake.pck"),
    ("cinderwake", ".godot/imported/original.png.ctex"),
    ("cinderwake", ".godot/shader_cache/derived"),
    ("a-loom", "graphify-out/graph.json"),
    ("agent-hub", ".dev-tools/cleanroom-pydeps/package.py"),
    ("browser-automation", ".dev-tools/npm-cache/content"),
    ("browser-automation", ".dev-tools/uv-cache/package.whl"),
    ("browser-automation", ".dev-tools/tiktoken-cache/encoding"),
    ("agent-hub", ".dev-tools/session-123-details.txt"),
])
def test_audited_generated_output_is_omitted(tmp_path: Path, source: str, path: str) -> None:
    assert _should_exclude(path, _load_excludes(tmp_path, source))


@pytest.mark.parametrize(("source", "path"), [
    ("summitflow", "host-monitor/Cargo.lock"),
    ("summitflow", "host-monitor/src/main.rs"),
    ("summitflow", "data/design-studio/original.png"),
    ("portfolio-ai", "data/household_uploads/transactions.csv"),
    ("portfolio-ai", "backend/app/storage/backups.py"),
    ("cinderwake", ".godot/export_credentials.cfg"),
    ("cinderwake", "project.godot"),
    ("cinderwake", "export_presets.cfg"),
    ("cinderwake", ".aloom/workspace/versions/original.json"),
    ("cinderwake", "art/pending/unpublished.png"),
    ("rootfall", "audio/original.wav"),
    ("the-aftertimes", ".dev-tools/agent_runs/unique-draft.json"),
    ("a-loom", "samples/aftertimes/workspace/versions/original.json"),
    ("learn-o-tron", "data/voice/pinned-model.onnx"),
    ("codex-config", "generated_images/original.png"),
    ("agent-hub", ".dev-tools/hatchet-src/local-change.py"),
    ("summitflow", ".dev-tools/backup-recovery-proof.json"),
    ("browser-automation", ".dev-tools/unique-draft.md"),
    ("unreviewed-project", "builds/web/original-source.js"),
    ("unreviewed-project", "data/backups/unique.bin"),
])
def test_originals_and_uncertain_work_remain(tmp_path: Path, source: str, path: str) -> None:
    assert not _should_exclude(path, _load_excludes(tmp_path, source))


def test_project_override_can_preserve_an_audited_output(tmp_path: Path) -> None:
    (tmp_path / ".backupignore").write_text("!./data/backups\n")
    assert not _should_exclude("data/backups/unique.bin", _load_excludes(tmp_path, "portfolio-ai"))


def test_audited_profiles_do_not_change_an_explicit_file_source(tmp_path: Path) -> None:
    source = tmp_path / "portfolio-ai"
    source.write_text("current configuration")
    assert "./data/backups" not in _load_excludes(source, "portfolio-ai")
