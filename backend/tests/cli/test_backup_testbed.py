"""Tests for testbed backup/reset CLI commands."""

from __future__ import annotations

import re

from typer.testing import CliRunner

runner = CliRunner()


def test_backup_testbed_baseline_compact(monkeypatch) -> None:
    from cli.main import app

    monkeypatch.setenv("ST_PROJECT_ID", "test2")
    monkeypatch.setattr(
        "cli.commands.backup_testbed.capture_testbed_baseline",
        lambda project_id, note=None, snapshot_name=None, allow_dirty=False, keep_local=False, local_only=True: {
            "project_id": project_id,
            "backup_id": "bkp-123",
            "backup_name": "test2-20260325-210000.tar.gz",
            "snapshot_id": "snap-123",
            "snapshot_name": "baseline",
            "archive_location": "/tmp/test2.tar.gz",
            "git_branch": "main",
            "git_head": "abc123",
            "git_dirty": allow_dirty,
        },
    )

    result = runner.invoke(app, ["backup", "testbed", "baseline", "--note", "Seed baseline"])

    assert result.exit_code == 0
    assert (
        "TESTBED_BASELINE bkp-123|snapshot:snap-123|branch:main|head:abc123|dirty:no"
        in result.output
    )


def test_backup_testbed_baseline_supports_remote_mode(monkeypatch) -> None:
    from cli.main import app

    monkeypatch.setenv("ST_PROJECT_ID", "test2")
    captured: dict[str, object] = {}

    def _fake_capture(
        project_id,
        note=None,
        snapshot_name=None,
        allow_dirty=False,
        keep_local=False,
        local_only=True,
    ):
        captured["local_only"] = local_only
        captured["keep_local"] = keep_local
        return {
            "project_id": project_id,
            "backup_id": "bkp-123",
            "backup_name": "test2-20260325-210000.tar.gz",
            "snapshot_id": "snap-123",
            "snapshot_name": "baseline",
            "archive_location": "/tmp/test2.tar.gz",
            "git_branch": "main",
            "git_head": "abc123",
            "git_dirty": False,
        }

    monkeypatch.setattr("cli.commands.backup_testbed.capture_testbed_baseline", _fake_capture)

    result = runner.invoke(app, ["backup", "testbed", "baseline", "--remote", "--keep-local"])

    assert result.exit_code == 0
    assert captured == {"local_only": False, "keep_local": True}


def test_backup_testbed_reset_uses_two_pass_confirmation(monkeypatch) -> None:
    from cli.main import app

    monkeypatch.setenv("ST_PROJECT_ID", "test2")

    preview_payload = {
        "project_id": "test2",
        "backup_id": "bkp-123",
        "backup_name": "test2-20260325-210000.tar.gz",
        "snapshot_id": "snap-123",
        "snapshot_name": "baseline",
        "project_root": "/srv/workspaces/projects/test2",
        "git_branch": "main",
        "git_head": "abc123",
        "has_database": True,
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "cli.commands.backup_testbed.preview_testbed_reset",
        lambda project_id, backup_id=None: preview_payload,
    )

    def _fake_reset(project_id: str, backup_id: str | None = None, rebuild: bool = True) -> dict[str, object]:
        captured["project_id"] = project_id
        captured["backup_id"] = backup_id
        captured["rebuild"] = rebuild
        return {
            "project_id": project_id,
            "backup_id": "bkp-123",
            "snapshot_id": "snap-123",
            "db_restored": True,
            "files_restored": True,
            "rebuild_ran": rebuild,
        }

    monkeypatch.setattr(
        "cli.commands.backup_testbed.reset_testbed_to_baseline",
        _fake_reset,
    )

    preview = runner.invoke(app, ["backup", "testbed", "reset"])
    assert preview.exit_code == 0
    assert "--confirm" in preview.output
    assert "test2" in preview.output
    assert "snap-123" in preview.output

    token_match = re.search(r"--confirm (\w+)", preview.output)
    assert token_match is not None
    token = token_match.group(1)

    result = runner.invoke(app, ["backup", "testbed", "reset", "--confirm", token])

    assert result.exit_code == 0
    assert "TESTBED_RESET bkp-123|snapshot:snap-123|db:yes|files:yes|rebuild:yes" in result.output
    assert captured == {"project_id": "test2", "backup_id": None, "rebuild": True}


def test_backup_testbed_reset_supports_explicit_backup_and_no_rebuild(monkeypatch) -> None:
    from cli.main import app

    monkeypatch.setenv("ST_PROJECT_ID", "test2")
    monkeypatch.setattr(
        "cli.commands.backup_testbed.preview_testbed_reset",
        lambda project_id, backup_id=None: {
            "project_id": project_id,
            "backup_id": backup_id,
            "backup_name": "test2-20260325-210000.tar.gz",
            "snapshot_id": "snap-123",
            "snapshot_name": "baseline",
            "project_root": "/srv/workspaces/projects/test2",
            "git_branch": "main",
            "git_head": "abc123",
            "has_database": False,
        },
    )
    monkeypatch.setattr(
        "cli.commands.backup_testbed.reset_testbed_to_baseline",
        lambda project_id, backup_id=None, rebuild=True: {
            "project_id": project_id,
            "backup_id": backup_id,
            "snapshot_id": "snap-123",
            "db_restored": False,
            "files_restored": True,
            "rebuild_ran": rebuild,
        },
    )

    preview = runner.invoke(app, ["backup", "testbed", "reset", "bkp-999", "--no-rebuild"])
    assert preview.exit_code == 0

    token_match = re.search(r"--confirm (\w+)", preview.output)
    assert token_match is not None
    token = token_match.group(1)

    result = runner.invoke(
        app,
        ["backup", "testbed", "reset", "bkp-999", "--no-rebuild", "--confirm", token],
    )

    assert result.exit_code == 0
    assert "TESTBED_RESET bkp-999|snapshot:snap-123|db:no|files:yes|rebuild:no" in result.output
