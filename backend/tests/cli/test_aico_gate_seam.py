"""`st check` and `st commit` call Aico's gate (`aico check|commit`) per verb, and fall back on exit 3."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cli.commands import check as check_command
from cli.lib import aico_delegate
from cli.main import app

runner = CliRunner()


@pytest.fixture
def aico(monkeypatch):
    """Aico on PATH with every gate verb on; records each call and answers with ``codes``."""
    monkeypatch.setenv("ST_AICO_CHECKS", "1")
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda name: f"/bin/{name}")
    calls: list[tuple[str, ...]] = []
    codes = [0]
    monkeypatch.setattr(aico_delegate, "run_checks", lambda *argv: calls.append(argv) or codes[0])
    return calls, codes


def test_each_verb_has_its_own_switch(monkeypatch):
    monkeypatch.setattr(aico_delegate.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(aico_delegate, "AICO_GATE_VERBS", frozenset({"check"}))
    monkeypatch.delenv("ST_AICO_CHECKS")
    assert aico_delegate.checks_enabled("check") and not aico_delegate.checks_enabled("commit")
    monkeypatch.setenv("ST_AICO_CHECKS", "0")
    assert not aico_delegate.checks_enabled("check")
    monkeypatch.setenv("ST_AICO_CHECKS", "1")
    assert aico_delegate.checks_enabled("commit")


def test_check_passes_the_options_aico_runs(aico):
    calls, codes = aico
    assert check_command._aico_check(["-q", "-d"]) == 0
    assert check_command._aico_check(["--check"]) == 0
    assert calls == [("check", "--quick", "--changed-only"), ("check",)]
    codes[0] = 1
    assert check_command._aico_check(["--quick"]) == 1


def test_check_keeps_summitflow_for_other_options_and_unhandled_repos(aico):
    calls, codes = aico
    # Acceptance stays SummitFlow's: deploys, publication and `st done` read its receipts.
    for args in ([], ["-d"], ["budget"], ["vitest"], ["--acceptance"], ["--acceptance", "--sha", "a"], ["--native", "--stage", "x"]):
        assert check_command._aico_check(args) is None
    assert calls == []
    codes[0] = aico_delegate.NOT_HANDLED
    assert check_command._aico_check(["--quick"]) is None


def test_commit_with_paths_goes_to_aico(aico):
    calls, codes = aico
    with patch("cli.lib.commit_workflow.commit_repo") as commit_repo:
        result = runner.invoke(app, ["commit", "-m", "Change a", "--paths", "a.py", "b.py", "--with-ack", "r1"])
        assert result.exit_code == 0
        assert calls == [("commit", "-m", "Change a", "--paths", "a.py", "b.py", "--with-ack", "r1")]
        commit_repo.assert_not_called()
        codes[0] = 1
        assert runner.invoke(app, ["commit", "-m", "x", "--paths", "a.py"]).exit_code == 1


@pytest.mark.parametrize("extra", [[], ["--task", "t1"], ["-R", "/elsewhere"]])
def test_commit_keeps_summitflow_without_paths_with_a_task_or_another_repo(aico, extra):
    calls, _codes = aico
    paths = [] if not extra else ["--paths", "a.py"]
    with (
        patch("cli.lib.commit_workflow.current_repo"),
        patch("cli.lib.commit_workflow.commit_repo", return_value={"status": "SUCCESS", "sha": "s"}) as commit_repo,
        patch("app.storage.events.log_task_event"),
    ):
        runner.invoke(app, ["commit", "-m", "x", *paths, *extra])
    assert calls == []
    commit_repo.assert_called_once()


def test_commit_falls_back_when_aico_does_not_run_the_repo(aico):
    calls, codes = aico
    codes[0] = aico_delegate.NOT_HANDLED
    with (
        patch("cli.lib.commit_workflow.current_repo"),
        patch("cli.lib.commit_workflow.commit_repo", return_value={"status": "SUCCESS", "sha": "s"}) as commit_repo,
    ):
        assert runner.invoke(app, ["commit", "-m", "x", "--paths", "a.py"]).exit_code == 0
    assert len(calls) == 1
    commit_repo.assert_called_once()


def test_acceptance_runs_summitflows_own_gate(monkeypatch, tmp_path):
    from cli.lib import acceptance

    seen = {}
    monkeypatch.setenv("ST_AICO_CHECKS", "1")
    monkeypatch.setattr(acceptance.subprocess, "run", lambda *a, **k: seen.update(k["env"]))
    acceptance._run(["st", "check", "--check"], tmp_path)
    assert seen["ST_AICO_CHECKS"] == "0"
