import pytest
from typer.testing import CliRunner

from cli.commands import backup_native_host


def test_native_host_dry_run_only_previews(monkeypatch):
    calls = []
    monkeypatch.setattr(backup_native_host, "run_native_host_backup", lambda **kwargs: calls.append(kwargs) or {"status": "preview", "ready": False})
    result = CliRunner().invoke(backup_native_host.app, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert calls == [{"dry_run": True}]


@pytest.mark.parametrize("status", ["blocked", "failed", "partial", "cancelled", "error"])
def test_native_host_incomplete_run_is_not_success(monkeypatch, status):
    monkeypatch.setattr(backup_native_host, "run_native_host_backup", lambda **kwargs: {"status": status, "reason": "capture-incomplete"})
    result = CliRunner().invoke(backup_native_host.app, ["run"])
    assert result.exit_code == 1
    assert "capture-incomplete" in result.stdout
