"""Accepted managed runtime pairing without launch or host spool access."""
from pathlib import Path

import pytest
import typer

from cli.commands import sessions


@pytest.fixture
def accepted_runtime(tmp_path, monkeypatch):
    state = tmp_path / "service-state"
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(state))
    source = state / "projects/summitflow/releases/accepted/source"
    python = source / "backend/.venv/bin/python"
    script = source / "scripts/codex-managed-session.py"
    python.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    python.write_text("private runtime fixture")
    python.chmod(0o700)
    script.write_text("managed script fixture")
    current = state / "projects/summitflow/current"
    current.symlink_to(source.parent)
    return state, source, python, script


def test_managed_runtime_selects_immutable_accepted_pair(accepted_runtime):
    _, source, python, script = accepted_runtime
    assert sessions._managed_codex_runtime() == (str(python), script)
    assert source.is_relative_to(python.parents[3])
    assert "/current/" not in str(python)


def test_managed_runtime_without_accepted_source_keeps_checkout_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("SUMMITFLOW_SERVICE_STATE_ROOT", str(tmp_path / "absent-state"))
    python, script = sessions._managed_codex_runtime()
    assert python == sessions.sys.executable
    assert script == Path(sessions.__file__).resolve().parents[3] / "scripts/codex-managed-session.py"


@pytest.mark.parametrize("missing", ["python", "script"])
def test_incomplete_accepted_runtime_cannot_mix_checkout_and_release(accepted_runtime, missing):
    _, _, python, script = accepted_runtime
    (python if missing == "python" else script).unlink()
    with pytest.raises(typer.BadParameter, match="accepted runtime incomplete"):
        sessions._managed_codex_runtime()


def test_managed_command_preserves_project_attribution_with_accepted_pair(accepted_runtime, tmp_path, monkeypatch):
    import os

    _, _, python, script = accepted_runtime
    project = tmp_path / "registered-project"
    project.mkdir()
    monkeypatch.setattr(sessions, "_binding_project", lambda: ("agent-hub", project))
    commands = []
    class ExecCalled(Exception):
        pass
    def execute(binary, arguments):
        commands.append((binary, arguments))
        raise ExecCalled
    monkeypatch.setattr(os, "execv", execute)
    with pytest.raises(ExecCalled):
        sessions.managed_codex(status=True)
    assert commands == [(str(python), [str(python), str(script), "--project", "agent-hub", "--project-root", str(project), "--status"])]
