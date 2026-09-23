from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from cli.lib import acceptance
from cli.main import app


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("value = 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def successful_runner(calls: list[list[str]]):
    def run(command: list[str], cwd: Path):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    return run


def test_accept_revision_writes_and_reuses_exact_source_receipt(repo: Path) -> None:
    calls: list[list[str]] = []
    sha = git(repo, "rev-parse", "HEAD")

    first = acceptance.accept_revision(
        repo, sha=sha, scope=("app.py",), task_id="task-one", runner=successful_runner(calls)
    )
    second = acceptance.accept_revision(
        repo,
        sha=sha,
        scope=("pyproject.toml",),
        task_id="task-two",
        runner=successful_runner(calls),
    )

    assert first["state"] == "success"
    assert first["source_commit"] == sha
    assert first["source_tree"] == git(repo, "rev-parse", "HEAD^{tree}")
    assert first["scope"] == ["app.py"]
    assert first["reused"] is False
    assert first["check_count"] == 1
    assert first["duration_ms"] >= 0
    assert first["checks"][0]["duration_ms"] >= 0
    assert Path(first["acceptance_artifact"]).is_file()
    assert second["acceptance_id"] == first["acceptance_id"]
    assert second["reused"] is True
    assert second["task_id"] == "task-two"
    assert second["scope"] == ["pyproject.toml"]
    assert second["reuse_lookup_ms"] >= 0
    assert calls == [["st", "check", "--check"]]


def test_accept_revision_rejects_dirty_candidate(repo: Path) -> None:
    (repo / "app.py").write_text("value = 2\n")

    with pytest.raises(acceptance.AcceptanceError, match="clean checkout"):
        acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))


def test_accept_revision_detects_checkout_mutation_during_checks(repo: Path) -> None:
    sha = git(repo, "rev-parse", "HEAD")

    def mutate(command: list[str], cwd: Path):
        (cwd / "app.py").write_text("value = 2\n")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    with pytest.raises(acceptance.AcceptanceError, match="source_changed_during_acceptance"):
        acceptance.accept_revision(repo, sha=sha, runner=mutate)


def test_validate_receipt_allows_later_checkout_to_advance(repo: Path) -> None:
    accepted_sha = git(repo, "rev-parse", "HEAD")
    receipt = acceptance.accept_revision(repo, sha=accepted_sha, runner=successful_runner([]))
    (repo / "later.py").write_text("later = True\n")
    git(repo, "add", "later.py")
    git(repo, "commit", "-qm", "later")

    validated = acceptance.validate_acceptance_receipt(repo, receipt, sha=accepted_sha)

    assert validated["state"] == "success"
    assert validated["source_commit"] == accepted_sha
    assert validated["source_tree"] != git(repo, "rev-parse", "HEAD^{tree}")


def test_validate_receipt_rejects_tampered_payload(repo: Path) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    payload = json.loads(Path(receipt["acceptance_artifact"]).read_text())
    payload["source"]["tree"] = "0" * 40

    with pytest.raises(acceptance.AcceptanceError, match="integrity"):
        acceptance.validate_acceptance_receipt(repo, payload)


@pytest.mark.parametrize("mutation", ["count", "missing", "command", "failed", "returncode", "plan"])
def test_receipt_success_label_does_not_override_actual_checks(repo: Path, mutation: str) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    payload = json.loads(Path(receipt["acceptance_artifact"]).read_text())
    if mutation == "count":
        payload["check_count"] = 0
    elif mutation == "missing":
        payload["checks"] = []
    elif mutation == "command":
        payload["checks"][0]["command"] = ["echo", "not a check"]
    elif mutation == "failed":
        payload["checks"][0]["state"] = "failed"
    elif mutation == "returncode":
        payload["checks"][0]["returncode"] = 7
    else:
        payload["plan"]["commands"] = [["echo", "not a check"]]
        payload["checks"][0]["command"] = payload["plan"]["commands"][0]
    payload["acceptance_id"] = acceptance._receipt_digest(payload)
    with pytest.raises(acceptance.AcceptanceError, match=r"checks|plan"):
        acceptance.validate_acceptance_receipt(repo, payload, sha="HEAD")


def test_done_reuses_explicit_receipt_without_touching_unrelated_wip(repo: Path, monkeypatch) -> None:
    from cli.commands import done_task

    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    (repo / "unrelated.txt").write_bytes(b"other agent work")
    git(repo, "add", "unrelated.txt")
    before = git(repo, "diff", "--cached", "--binary")
    monkeypatch.setattr(done_task, "_checkpoint_repo_root", lambda _: str(repo))
    stored = Mock()
    monkeypatch.setattr("app.storage.tasks.closeout.store_verification", stored)
    monkeypatch.setattr(acceptance, "accept_revision", Mock(side_effect=AssertionError("do not repeat checks")))
    result = done_task._accept_completed_work("task", "project", paths=("app.py",), acceptance_receipt=receipt)
    assert result["source_commit"] == git(repo, "rev-parse", "HEAD")
    assert result["reused"] is True
    assert (repo / "unrelated.txt").read_bytes() == b"other agent work"
    assert git(repo, "diff", "--cached", "--binary") == before
    stored.assert_called_once()


@pytest.mark.parametrize("blocker", ["no-paths", "selected-dirty", "head-changed"])
def test_done_receipt_cannot_bypass_scope_or_new_checkpoint(repo: Path, monkeypatch, blocker: str) -> None:
    from cli.commands import done_task

    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    paths = () if blocker == "no-paths" else ("app.py",)
    if blocker != "no-paths":
        (repo / "app.py").write_text("value = 2\n")
        if blocker == "head-changed":
            git(repo, "add", "app.py")
            git(repo, "commit", "-qm", "task checkpoint")
    monkeypatch.setattr(done_task, "_checkpoint_repo_root", lambda _: str(repo))
    stored = Mock()
    monkeypatch.setattr("app.storage.tasks.closeout.store_verification", stored)
    with pytest.raises((ValueError, acceptance.AcceptanceError)):
        done_task._accept_completed_work("task", "project", paths=paths, acceptance_receipt=receipt)
    stored.assert_not_called()


def test_changed_local_acceptance_plan_invalidates_receipt(repo: Path, monkeypatch) -> None:
    receipt = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    monkeypatch.setattr(
        acceptance,
        "_acceptance_plan",
        lambda: {"commands": [], "toolchain": {}, "fingerprint": "changed"},
    )

    with pytest.raises(acceptance.AcceptanceError, match="toolchain changed"):
        acceptance.validate_acceptance_receipt(repo, receipt)


def test_failed_full_gate_raises_and_retains_bounded_evidence(repo: Path) -> None:
    def fail(command: list[str], _cwd: Path):
        return subprocess.CompletedProcess(command, 7, "x" * 5000, "failed")

    with pytest.raises(acceptance.AcceptanceError, match="acceptance_checks_failed") as error:
        acceptance.accept_revision(repo, sha="HEAD", runner=fail)

    artifact = Path(str(error.value).split("acceptance evidence: ", 1)[1])
    payload = json.loads(artifact.read_text())
    assert payload["state"] == "failed"
    assert payload["checks"][0]["returncode"] == 7
    assert len(payload["checks"][0]["detail"]) == 1200
    assert payload["checks"][0]["output_bytes"] == 5007


def test_later_success_does_not_overwrite_failed_acceptance_evidence(repo: Path) -> None:
    def fail(command, _cwd):
        return subprocess.CompletedProcess(command, 1, "failure artifact remains useful", "")

    with pytest.raises(acceptance.AcceptanceError) as error:
        acceptance.accept_revision(repo, sha="HEAD", runner=fail)
    failed_path = Path(str(error.value).split("acceptance evidence: ", 1)[1])
    failed_bytes = failed_path.read_bytes()
    successful = acceptance.accept_revision(repo, sha="HEAD", runner=successful_runner([]))
    assert Path(successful["acceptance_artifact"]) != failed_path
    assert failed_path.read_bytes() == failed_bytes
    assert json.loads(failed_bytes)["state"] == "failed"


def test_repo_lock_reports_concurrent_mutation(repo: Path) -> None:
    with (
        acceptance.repo_lock(repo, purpose="first"),
        pytest.raises(acceptance.AcceptanceError, match="repo_mutation_in_progress"),
        acceptance.repo_lock(repo, purpose="second"),
    ):
        pass


def test_check_acceptance_surface_forwards_exact_source(repo: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def accept(root: Path, **kwargs: object) -> dict[str, object]:
        captured.update({"root": root, **kwargs})
        return {
            "state": "success",
            "source_commit": "a" * 40,
            "acceptance_id": "acceptance-one",
            "acceptance_artifact": "/tmp/acceptance-one.json",
            "reused": True,
            "duration_ms": 12.5,
            "check_count": 1,
            "inputs": {"large_manifest": "must-not-be-printed"},
            "checks": [{"detail": "must-not-be-printed"}],
        }

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr("cli.commands.check.accept_revision", accept)
    monkeypatch.setattr(
        "cli.commands.check.renew_owned_claim",
        lambda root, task_id: captured.update({"renewed_root": root, "renewed_task": task_id}),
    )
    result = CliRunner().invoke(
        app,
        [
            "check",
            "--acceptance",
            "--sha",
            "abc",
            "--task",
            "task-one",
            "--scope",
            "backend",
            "--no-reuse",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "root": repo,
        "sha": "abc",
        "task_id": "task-one",
        "scope": ["backend"],
        "reuse": False,
        "renewed_root": repo,
        "renewed_task": "task-one",
    }
    assert result.stdout == (
        "ACCEPTANCE:state=success|source="
        + "a" * 40
        + "|id=acceptance-one|artifact=/tmp/acceptance-one.json|"
        "reused=true|duration_ms=12.5|checks=1\n"
    )


def test_check_acceptance_json_preserves_full_machine_receipt(repo: Path, monkeypatch) -> None:
    receipt: dict[str, object] = {
        "state": "success",
        "source_commit": "a" * 40,
        "inputs": {"fingerprint": "input-one"},
        "checks": [{"detail": "retained detail"}],
    }
    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr("cli.commands.check.accept_revision", lambda *_args, **_kwargs: receipt)

    result = CliRunner().invoke(app, ["check", "--acceptance", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout.removeprefix("ACCEPTANCE:")) == receipt


def test_check_acceptance_blocks_when_owned_claim_cannot_be_renewed(
    repo: Path, monkeypatch
) -> None:
    from cli.lib.task_claims import TaskClaimRenewalError

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr(
        "cli.commands.check.renew_owned_claim",
        lambda *_args: (_ for _ in ()).throw(TaskClaimRenewalError("claim lost")),
    )
    accept = Mock()
    monkeypatch.setattr("cli.commands.check.accept_revision", accept)

    result = CliRunner().invoke(app, ["check", "--acceptance", "--task", "task-one"])

    assert result.exit_code == 2
    assert "claim lost" in result.stderr
    accept.assert_not_called()


def test_check_acceptance_help_is_available_without_running_checks() -> None:
    result = CliRunner().invoke(app, ["check", "--acceptance", "--help"])

    assert result.exit_code == 0
    assert "Usage: st check --acceptance" in result.stdout
    assert "--no-reuse" in result.stdout
    assert "--json" in result.stdout
