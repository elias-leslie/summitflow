from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
        return {"state": "success", "source_commit": "a" * 40}

    monkeypatch.setattr("cli.commands.check._resolve_repo_root", lambda: repo)
    monkeypatch.setattr("cli.commands.check.accept_revision", accept)
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
    }
    assert result.stdout.startswith("ACCEPTANCE:")


def test_check_acceptance_help_is_available_without_running_checks() -> None:
    result = CliRunner().invoke(app, ["check", "--acceptance", "--help"])

    assert result.exit_code == 0
    assert "Usage: st check --acceptance" in result.stdout
    assert "--no-reuse" in result.stdout
