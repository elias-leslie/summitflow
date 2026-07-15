"""Tests for the explicit current-Codex-session binding command."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.client import APIError
from cli.config import set_project_override
from cli.main import app

runner = CliRunner()

_THREAD_ID = "019f62d8-881c-7393-8c19-ae9b2b21e56b"
_PROJECT_ID = "rootfall"
_PROJECT_ROOT = "/srv/workspaces/projects/rootfall"


@pytest.fixture(autouse=True)
def _reset_project_override() -> Iterator[None]:
    set_project_override(None)
    yield
    set_project_override(None)


def _active_session(*, project_id: str = _PROJECT_ID) -> dict[str, str]:
    return {"id": _THREAD_ID, "project_id": project_id, "status": "active"}


def test_bind_current_syncs_absent_session_and_requires_active_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    client = MagicMock()
    client.get_session.side_effect = [
        APIError(404, "not found"),
        _active_session(),
    ]
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="synced", stderr="")

    with (
        patch.object(sessions_cmd, "STClient", return_value=client) as client_cls,
        patch.object(sessions_cmd, "get_project_override", return_value=_PROJECT_ID),
        patch.object(sessions_cmd, "get_config") as get_config,
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT),
        patch.object(sessions_cmd.subprocess, "run", return_value=completed) as run,
    ):
        result = runner.invoke(app, ["-P", _PROJECT_ID, "sessions", "bind", "current"])

    assert result.exit_code == 0
    assert (
        f"SESSION_BIND:{_THREAD_ID}|project={_PROJECT_ID}|status=active|result=bound"
        in result.output
    )
    get_config.assert_not_called()
    client_cls.assert_called_once_with(require_project=False)
    assert client.get_session.call_args_list == [
        ((_THREAD_ID,), {}),
        ((_THREAD_ID,), {}),
    ]
    run.assert_called_once_with(
        [
            str(sessions_cmd._CODEX_SESSION_SYNC),
            "--bind-session",
            _THREAD_ID,
            "--bind-project",
            _PROJECT_ID,
            "--project-root",
            _PROJECT_ROOT,
            "--force",
            "--verbose",
        ],
        cwd=Path(sessions_cmd._CODEX_SESSION_SYNC).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )


def test_bind_current_refreshes_local_binding_for_existing_active_project_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    client = MagicMock()
    client.get_session.return_value = _active_session()
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="synced", stderr="")

    with (
        patch.object(sessions_cmd, "STClient", return_value=client),
        patch.object(sessions_cmd, "get_project_override", return_value=_PROJECT_ID),
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT),
        patch.object(sessions_cmd.subprocess, "run", return_value=completed) as run,
    ):
        result = runner.invoke(app, ["sessions", "bind"])

    assert result.exit_code == 0
    assert "status=active|result=refreshed" in result.output
    assert client.get_session.call_count == 2
    run.assert_called_once()


def test_bind_current_rejects_existing_session_owned_by_another_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    client = MagicMock()
    client.get_session.return_value = _active_session(project_id="the-aftertimes")

    with (
        patch.object(sessions_cmd, "STClient", return_value=client),
        patch.object(sessions_cmd, "get_project_override", return_value=_PROJECT_ID),
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT),
        patch.object(sessions_cmd.subprocess, "run") as run,
    ):
        result = runner.invoke(app, ["sessions", "bind", "current"])

    assert result.exit_code == 1
    assert "belongs to project the-aftertimes, not rootfall" in result.output
    run.assert_not_called()


def test_bind_accepts_only_current_literal_or_exact_current_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    with patch.object(sessions_cmd, "STClient") as client_cls:
        rejected = runner.invoke(app, ["sessions", "bind", "019f62d8"])

    assert rejected.exit_code == 1
    assert "Only 'current' or the exact CODEX_THREAD_ID may be bound" in rejected.output
    client_cls.assert_not_called()

    client = MagicMock()
    client.get_session.return_value = _active_session()
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="synced", stderr="")
    with (
        patch.object(sessions_cmd, "STClient", return_value=client),
        patch.object(sessions_cmd, "get_project_override", return_value=_PROJECT_ID),
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT),
        patch.object(sessions_cmd.subprocess, "run", return_value=completed),
    ):
        accepted = runner.invoke(app, ["sessions", "bind", _THREAD_ID])

    assert accepted.exit_code == 0
    assert "result=refreshed" in accepted.output


def test_bind_requires_codex_thread_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    with patch.object(sessions_cmd, "STClient") as client_cls:
        result = runner.invoke(app, ["sessions", "bind", "current"])

    assert result.exit_code == 1
    assert "CODEX_THREAD_ID is not set" in result.output
    client_cls.assert_not_called()


def test_bind_falls_back_to_config_project_and_requires_registered_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    config = SimpleNamespace(project_id=_PROJECT_ID)

    with (
        patch.object(sessions_cmd, "get_project_override", return_value=None),
        patch.object(sessions_cmd, "get_config", return_value=config) as get_config,
        patch.object(sessions_cmd, "get_project_root_path", return_value=None) as get_root,
        patch.object(sessions_cmd, "STClient") as client_cls,
    ):
        result = runner.invoke(app, ["sessions", "bind", "current"])

    assert result.exit_code == 1
    assert "has no registered root path" in result.output
    get_config.assert_called_once_with()
    get_root.assert_called_once_with(_PROJECT_ID)
    client_cls.assert_not_called()


def test_bind_honors_sessions_level_project_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    client = MagicMock()
    client.get_session.return_value = _active_session()
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="synced", stderr="")

    with (
        patch.object(sessions_cmd, "STClient", return_value=client),
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT) as root,
        patch.object(sessions_cmd.subprocess, "run", return_value=completed),
    ):
        result = runner.invoke(
            app,
            ["sessions", "-P", _PROJECT_ID, "bind", "current"],
        )

    assert result.exit_code == 0
    root.assert_called_once_with(_PROJECT_ID)
    assert "project=rootfall" in result.output


def test_bind_surfaces_sync_failure_without_claiming_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    client = MagicMock()
    client.get_session.side_effect = APIError(404, "not found")
    completed = subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="bad bind")

    with (
        patch.object(sessions_cmd, "STClient", return_value=client),
        patch.object(sessions_cmd, "get_project_override", return_value=_PROJECT_ID),
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT),
        patch.object(sessions_cmd.subprocess, "run", return_value=completed),
    ):
        result = runner.invoke(app, ["sessions", "bind", "current"])

    assert result.exit_code == 1
    assert "Codex session sync failed (2): bad bind" in result.output
    assert "SESSION_BIND:" not in result.output


def test_bind_rejects_inactive_post_sync_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands import sessions as sessions_cmd

    monkeypatch.setenv("CODEX_THREAD_ID", _THREAD_ID)
    inactive = {"id": _THREAD_ID, "project_id": _PROJECT_ID, "status": "completed"}
    client = MagicMock()
    client.get_session.side_effect = [APIError(404, "not found"), inactive]
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="synced", stderr="")

    with (
        patch.object(sessions_cmd, "STClient", return_value=client),
        patch.object(sessions_cmd, "get_project_override", return_value=_PROJECT_ID),
        patch.object(sessions_cmd, "get_project_root_path", return_value=_PROJECT_ROOT),
        patch.object(sessions_cmd.subprocess, "run", return_value=completed),
    ):
        result = runner.invoke(app, ["sessions", "bind", "current"])

    assert result.exit_code == 1
    assert f"Session {_THREAD_ID} is completed, not active" in result.output
    assert "SESSION_BIND:" not in result.output
