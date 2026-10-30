"""Characterization tests for the `st check` mode dispatch in cli.commands.check."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.main import app


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    (tmp_path / "app.py").write_text("value = 2\n")
    _git(tmp_path, "commit", "-qam", "second")
    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: tmp_path)
    return tmp_path


def _invoke(*args: str):
    return CliRunner().invoke(app, ["check", *args])


# --- --acceptance -----------------------------------------------------------


@pytest.fixture
def accept(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {"receipt": {"state": "success", "source_commit": "a" * 40}}

    def fake(root: Path, **kwargs: object) -> Mock:
        captured.update({"root": root, **kwargs})
        return Mock(to_dict=lambda: captured["receipt"])

    monkeypatch.setattr("cli.lib.acceptance_coordinator.accept_source", fake)
    return captured


@pytest.mark.parametrize("args,message", [
    (["--bogus"], "Unknown or incomplete st check --acceptance option: --bogus"),
    (["--sha"], "Unknown or incomplete st check --acceptance option: --sha"),
    (["--json", "--stage"], "Unknown or incomplete st check --acceptance option: --stage"),
    (["--coverage", "bogus"], "Acceptance coverage must be task or full"),
])
def test_acceptance_rejects_invalid_options_before_running(repo: Path, accept: dict[str, object],
                                                           args: list[str], message: str) -> None:
    result = _invoke("--acceptance", *args)
    assert result.exit_code == 2
    assert message in result.stderr
    assert "root" not in accept


def test_acceptance_accumulates_repeated_options(repo: Path, accept: dict[str, object]) -> None:
    result = _invoke("--acceptance", "--stage", "one", "--scope", "a", "--coverage", "task",
                     "--stage", "two", "--scope", "b")
    assert result.exit_code == 0, result.output
    assert accept["required_stages"] == ["one", "two"]
    assert accept["scope"] == ["a", "b"]
    assert accept["coverage"] == "task"
    assert accept["sha"] == "HEAD"
    assert accept["task_id"] == ""
    assert accept["reuse"] is True
    assert accept["materialization"] == "actual"
    assert result.stdout.startswith("ACCEPTANCE:state=success|source=" + "a" * 40)


def test_historical_full_acceptance_needs_no_task_and_runs_isolated(repo: Path, accept: dict[str, object]) -> None:
    # Publishing an older accepted commit re-accepts exactly that commit.
    result = _invoke("--acceptance", "--sha", "HEAD~1")
    assert result.exit_code == 0, result.output
    assert accept["materialization"] == "isolated"
    assert accept["sha"] == "HEAD~1"
    assert accept["task_id"] == ""
    assert accept["coverage"] == "full"


def test_historical_acceptance_with_task_and_scope_is_isolated(repo: Path, accept: dict[str, object],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cli.commands.check.renew_owned_claim", lambda *_args: None)
    result = _invoke("--acceptance", "--sha", "HEAD~1", "--task", "task-one", "--scope", "app.py")
    assert result.exit_code == 0, result.output
    assert accept["materialization"] == "isolated"
    assert accept["sha"] == "HEAD~1"


def test_head_sha_spelled_explicitly_is_not_historical(repo: Path, accept: dict[str, object]) -> None:
    result = _invoke("--acceptance", "--sha", _git(repo, "rev-parse", "HEAD"))
    assert result.exit_code == 0, result.output
    assert accept["materialization"] == "actual"


@pytest.mark.parametrize("dirty", ["modified", "untracked"])
def test_dirty_tree_acceptance_is_isolated(repo: Path, accept: dict[str, object], dirty: str) -> None:
    (repo / ("app.py" if dirty == "modified" else "new.py")).write_text("value = 3\n")
    result = _invoke("--acceptance")
    assert result.exit_code == 0, result.output
    assert accept["materialization"] == "isolated"


def test_failed_acceptance_exits_one(repo: Path, accept: dict[str, object]) -> None:
    accept["receipt"] = {"state": "failure"}
    result = _invoke("--acceptance")
    assert result.exit_code == 1
    assert result.stdout.startswith("ACCEPTANCE:state=failure|")


def test_acceptance_error_exits_two(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.lib.acceptance import AcceptanceError

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AcceptanceError("source moved")

    monkeypatch.setattr("cli.lib.acceptance_coordinator.accept_source", fail)
    result = _invoke("--acceptance")
    assert result.exit_code == 2
    assert "source moved" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("state,attached,warned", [
    ("success", True, False),
    ("success", False, True),
    ("failure", False, False),
])
def test_owned_task_acceptance_attaches_successful_proof(repo: Path, accept: dict[str, object],
                                                         monkeypatch: pytest.MonkeyPatch,
                                                         state: str, attached: bool, warned: bool) -> None:
    owned = {"id": "task-one"}
    attach = Mock(return_value=attached)
    accept["receipt"] = {"state": state}
    monkeypatch.setattr("cli.commands.check.renew_owned_claim", lambda root, task_id: owned)
    monkeypatch.setattr("cli.lib.task_claims.attach_owned_acceptance", attach)
    result = _invoke("--acceptance", "--task", "task-one")
    assert result.exit_code == (0 if state == "success" else 1)
    if state == "success":
        attach.assert_called_once_with(repo, owned, {"state": state})
    else:
        attach.assert_not_called()
    assert ("task proof was not attached" in result.stderr) is warned


def test_historical_acceptance_renews_claim_before_git_and_always_reads_status(
        repo: Path, accept: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.lib import commit_workflow

    calls: list[str] = []
    real_run_git = commit_workflow.run_git

    def recording_run_git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(" ".join(args[:2]) if args[0] == "rev-parse" else args[0])
        return real_run_git(root, args)

    monkeypatch.setattr("cli.commands.check.renew_owned_claim", lambda *_args: calls.append("renew"))
    monkeypatch.setattr("cli.lib.commit_workflow.run_git", recording_run_git)
    result = _invoke("--acceptance", "--sha", "HEAD~1", "--task", "task-one", "--scope", "app.py")
    assert result.exit_code == 0, result.output
    assert calls == ["renew", "rev-parse --verify", "rev-parse HEAD", "status"]


def _git_result(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


@pytest.mark.parametrize("selected,head,status,expected", [
    (_git_result(1), _git_result(0, "b\n"), _git_result(0, ""), "actual"),
    (_git_result(1), _git_result(0, "b\n"), _git_result(0, " M app.py\n"), "isolated"),
    (_git_result(0, "b\n"), _git_result(1), _git_result(0, ""), "actual"),
    (_git_result(0, "b\n"), _git_result(0, "b\n"), _git_result(128, " M app.py\n"), "actual"),
    (_git_result(0, "a\n"), _git_result(0, "b\n"), _git_result(128), "isolated"),
])
def test_acceptance_materialization_with_failed_git_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                          selected: subprocess.CompletedProcess[str],
                                                          head: subprocess.CompletedProcess[str],
                                                          status: subprocess.CompletedProcess[str],
                                                          expected: str) -> None:
    from cli.commands.check import _acceptance_materialization

    results = iter([selected, head, status])
    monkeypatch.setattr("cli.lib.commit_workflow.run_git", lambda *_args, **_kwargs: next(results))
    assert _acceptance_materialization(tmp_path, "rev") == expected


def test_clean_head_follows_the_projects_isolated_basis(repo: Path, accept: dict[str, object]) -> None:
    (repo / ".st-check.toml").write_text('[acceptance]\nbasis = "isolated"\n')
    _git(repo, "add", ".st-check.toml")
    _git(repo, "commit", "-qm", "opt in")
    result = _invoke("--acceptance")
    assert result.exit_code == 0, result.output
    assert accept["materialization"] == "isolated"


def test_parse_acceptance_args_maps_options_and_help() -> None:
    from cli.commands.check import _AcceptanceOptions, _parse_acceptance_args

    assert _parse_acceptance_args(["--json", "--help"]) == 0
    assert _parse_acceptance_args(["--sha", "abc", "--task", "task-one", "--scope", "a", "--coverage", "task",
                                   "--stage", "s", "--no-reuse", "--json"]) == _AcceptanceOptions(
        sha="abc", task_id="task-one", scope=["a"], coverage="task", required_stages=["s"], reuse=False,
        json_output=True)


# --- --deep -----------------------------------------------------------------


def _deep_result(state: str) -> dict[str, object]:
    return {"state": state, "stages": [
        {"state": state, "id": "slow-tests", "reason": "ran", "duration_ms": 5, "failures": ["first", "second"]},
    ]}


@pytest.mark.parametrize("state,code", [("pass", 0), ("fail", 1)])
@pytest.mark.parametrize("json_output", [False, True])
def test_deep_prints_stages_and_optional_evidence(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                                  state: str, code: int, json_output: bool) -> None:
    seen: list[Path] = []
    monkeypatch.setattr("cli.lib.deep_lane.run_deep", lambda root: seen.append(root) or _deep_result(state))
    result = _invoke("--deep", *(["--json"] if json_output else []))
    assert result.exit_code == code
    assert seen == [repo]
    lines = result.stdout.splitlines()
    assert lines[:3] == [f"DEEP:{state}:slow-tests|reason:ran|duration_ms:5", "  first", "  second"]
    if json_output:
        assert json.loads(lines[3].removeprefix("DEEP_EVIDENCE:")) == _deep_result(state)
    assert len(lines) == (4 if json_output else 3)


def test_deep_lane_error_exits_two(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.lib.deep_lane import DeepLaneError

    def fail(_root: Path) -> None:
        raise DeepLaneError("no deep stages declared")

    monkeypatch.setattr("cli.lib.deep_lane.run_deep", fail)
    result = _invoke("--deep")
    assert result.exit_code == 2
    assert "no deep stages declared" in result.stderr
    assert result.stdout == ""


# --- budget / --ci-repro / fallthrough -------------------------------------


@pytest.mark.parametrize("args,json_output", [(["budget"], False), (["budget", "--json"], True)])
def test_budget_delegates_to_quality_budget_report(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                                   args: list[str], json_output: bool) -> None:
    calls: list[tuple[Path, bool]] = []
    monkeypatch.setattr("cli.lib.quality_budget.report",
                        lambda root, *, json_output: calls.append((root, json_output)) or 3)
    result = _invoke(*args)
    assert result.exit_code == 3
    assert calls == [(repo, json_output)]


def test_ci_repro_delegates_remaining_args(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("cli.commands.check._ci_repro", lambda args, configs: calls.append(args) or 4)
    result = _invoke("--ci-repro", "--seed", "7")
    assert result.exit_code == 4
    assert calls == [["--seed", "7"]]


@pytest.mark.parametrize("args", [["pytest", "--help"], ["vitest", "-h"], ["semgrep", "--help"]])
def test_gate_help_prints_usage_without_running_the_tool(repo: Path, monkeypatch: pytest.MonkeyPatch,
                                                         args: list[str]) -> None:
    ran = Mock(return_value=0)
    monkeypatch.setattr("cli.commands.check_dispatch.run_named_tool", ran)
    result = _invoke(*args)
    assert result.exit_code == 0
    assert f"Usage: st check {args[0]} [--changed-only] [-- <{args[0]} args>]" in result.output
    ran.assert_not_called()


# --- native gates -----------------------------------------------------------


def _native_result(state: str = "pass") -> dict[str, object]:
    return {"state": state, "stages": [{"state": state, "id": "suite", "coverage": "full", "reason": "ran"}]}


@pytest.fixture
def native(repo: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    captured: dict[str, object] = {"plan": {"legacy_tools": []}, "result": _native_result()}

    def run(root: Path, plan: dict[str, object], **kwargs: object) -> dict[str, object]:
        captured.update({"root": root, "run_plan": plan, **kwargs})
        return dict(cast(dict[str, object], captured["result"]))

    monkeypatch.setattr("cli.commands.check.native_plan", lambda root: captured["plan"])
    monkeypatch.setattr("cli.commands.check.run_native", run)
    monkeypatch.delenv("ST_NATIVE_NO_REUSE", raising=False)
    return captured


@pytest.mark.parametrize("flag", ["--check", "-c"])
def test_native_full_gate_prints_stage_lines_and_evidence(native: dict[str, object], flag: str) -> None:
    result = _invoke(flag)
    assert result.exit_code == 0, result.output
    assert native["stage_id"] is None
    assert native["reuse"] is True
    assert native["full_gate"] is True
    lines = result.stdout.splitlines()
    assert lines[0] == "NATIVE:pass:suite|coverage:full|reason:ran"
    assert json.loads(lines[1].removeprefix("NATIVE_EVIDENCE:")) == _native_result()


def test_native_stage_with_json_and_no_reuse(native: dict[str, object]) -> None:
    native["result"] = _native_result("fail")
    result = _invoke("--native", "--no-reuse", "--stage", "suite", "--json")
    assert result.exit_code == 1
    assert native["stage_id"] == "suite"
    assert native["reuse"] is False
    assert native["full_gate"] is False
    assert result.stdout.startswith("NATIVE_EVIDENCE:")
    assert len(result.stdout.splitlines()) == 1


def test_native_reuse_can_be_disabled_by_environment(native: dict[str, object],
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ST_NATIVE_NO_REUSE", "1")
    assert _invoke("--native", "--json").exit_code == 0
    assert native["reuse"] is False


@pytest.mark.parametrize("args", [
    ["--check", "--changed-only"],
    ["-c", "--stage", "suite"],
    ["--native", "--stage"],
    ["--native", "--stage", "a", "b"],
    ["--native", "backend"],
])
def test_native_rejects_scope_arguments(native: dict[str, object], args: list[str]) -> None:
    result = _invoke(*args)
    assert result.exit_code == 2
    assert "native full gates do not accept scope/fix arguments" in result.stderr
    assert "root" not in native


def test_native_without_declaration_exits_two(native: dict[str, object]) -> None:
    native["plan"] = None
    result = _invoke("--native")
    assert result.exit_code == 2
    assert "project has no versioned native stage declaration" in result.stderr


def test_invalid_native_declaration_exits_two(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cli.commands.check_native import NativeCheckError

    def fail(_root: Path) -> None:
        raise NativeCheckError("bad declaration")

    monkeypatch.setattr("cli.commands.check.native_plan", fail)
    result = _invoke("--check")
    assert result.exit_code == 2
    assert "bad declaration" in result.stderr


@pytest.mark.parametrize("flag", ["--check", "-c"])
def test_full_gate_without_declaration_falls_through(native: dict[str, object],
                                                     monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    native["plan"] = None
    calls: list[list[str]] = []
    monkeypatch.setattr("cli.commands.check.handle_check_args",
                        lambda ctx, configs, *, runtime: calls.append(list(ctx.args)) or 5)
    result = _invoke(flag)
    assert result.exit_code == 5
    assert calls == [[flag]]


def test_ordinary_args_fall_through(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr("cli.commands.check.handle_check_args",
                        lambda ctx, configs, *, runtime: calls.append(list(ctx.args)) or 6)
    result = _invoke("ruff", "--", "backend")
    assert result.exit_code == 6
    assert calls and calls[0][0] == "ruff"


@pytest.mark.parametrize("legacy_state,blocked", [("pass", False), ("fail", True)])
def test_full_gate_runs_legacy_tools_first(native: dict[str, object], monkeypatch: pytest.MonkeyPatch,
                                           legacy_state: str, blocked: bool) -> None:
    native["plan"] = {"legacy_tools": ["ruff"]}
    legacy = {"state": legacy_state}
    printed: list[bool] = []

    def legacy_checks(root, plan, configs, *, print_output):
        printed.append(print_output)
        return legacy

    monkeypatch.setattr("cli.commands.check._native_legacy_checks", legacy_checks)
    monkeypatch.setattr("cli.commands.check.blocked_native_result",
                        lambda plan, reason: {"state": "fail", "stages": [], "blocked": reason})
    result = _invoke("--check", "--json")
    evidence = json.loads(result.stdout.removeprefix("NATIVE_EVIDENCE:"))
    assert printed == [False]
    assert evidence["legacy"] == legacy
    if blocked:
        assert result.exit_code == 1
        assert evidence["blocked"] == "cheap_legacy_gate_failed"
        assert "root" not in native
    else:
        assert result.exit_code == 0
        assert native["full_gate"] is True


def test_focused_native_stage_skips_legacy_tools(native: dict[str, object], monkeypatch: pytest.MonkeyPatch) -> None:
    native["plan"] = {"legacy_tools": ["ruff"]}
    legacy = Mock()
    monkeypatch.setattr("cli.commands.check._native_legacy_checks", legacy)
    result = _invoke("--native", "--json")
    assert result.exit_code == 0
    legacy.assert_not_called()
    assert "legacy" not in json.loads(result.stdout.removeprefix("NATIVE_EVIDENCE:"))
