"""Tests for Veeam backup CLI commands."""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

runner = CliRunner()


def _status_payload(
    *,
    active: dict[str, Any] | None = None,
    last: dict[str, Any] | None = None,
    can_start: bool = True,
) -> dict[str, Any]:
    return {
        "installed": True,
        "version": "6.3.2.1307",
        "service_active": True,
        "secure_boot_enabled": False,
        "mok_enrolled": False,
        "mok_enrollment_pending": False,
        "module_loaded": True,
        "module_signer": "test",
        "repository_name": "SummitFlowSystemImage",
        "repository_path": "/backup",
        "repository_accessible": True,
        "job_name": "SummitFlowSystemImage",
        "job_configured": True,
        "job_id": "job-1",
        "schedule_summary": "Daily at 02:00",
        "protected_objects": ["/dev/nvme0n1"],
        "last_session": last,
        "active_session": active,
        "can_start": can_start,
        "blocked_reason": None,
        "next_action": "Ready to start; scheduled daily at 02:00.",
    }


def test_backup_veeam_status_compact(monkeypatch) -> None:
    from cli.main import app

    class FakeAPI:
        def status(self) -> dict[str, Any]:
            return _status_payload(
                last={"id": "session-1", "state": "Success", "job_name": "SummitFlowSystemImage"}
            )

    monkeypatch.setattr("cli.commands.backup_veeam._api", lambda: FakeAPI())

    result = runner.invoke(app, ["backup", "veeam", "status"])

    assert result.exit_code == 0
    assert "VEEAM_STATUS|installed=yes|service=yes|repo=yes|job=yes|can_start=yes" in result.output
    assert "|last=Success:session-1|" in result.output


def test_backup_veeam_start_waits_for_completion(monkeypatch) -> None:
    from cli.main import app

    active = {"id": "session-2", "state": "Running", "job_name": "SummitFlowSystemImage"}
    complete = {"id": "session-2", "state": "Success", "job_name": "SummitFlowSystemImage"}

    class FakeAPI:
        def __init__(self) -> None:
            self.status_calls = 0

        def start(self) -> dict[str, Any]:
            return {"status": "started", "message": "started", "session_id": "session-2"}

        def status(self) -> dict[str, Any]:
            self.status_calls += 1
            if self.status_calls == 1:
                return _status_payload(active=active, last=active, can_start=False)
            return _status_payload(last=complete)

    fake_api = FakeAPI()
    monkeypatch.setattr("cli.commands.backup_veeam._api", lambda: fake_api)
    monkeypatch.setattr("cli.commands.backup_veeam.time.sleep", lambda _seconds: None)

    result = runner.invoke(
        app,
        ["backup", "veeam", "start", "--wait", "--poll-seconds", "1", "--timeout-minutes", "1"],
    )

    assert result.exit_code == 0
    assert "VEEAM_START|status=started|session=session-2" in result.output
    assert "VEEAM_WAIT|elapsed=" in result.output
    assert "VEEAM_DONE|installed=yes" in result.output
    assert "|last=Success:session-2|" in result.output


def test_backup_veeam_usage_manifest_includes_surface(monkeypatch) -> None:
    from cli.main import app

    result = runner.invoke(
        app,
        ["tools", "manifest", "--surface", "st.backup.veeam", "--format", "json"],
    )

    assert result.exit_code == 0
    assert "st.backup.veeam" in result.output
    assert "st backup veeam start --wait" in result.output
