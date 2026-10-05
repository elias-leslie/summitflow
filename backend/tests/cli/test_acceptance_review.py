"""Independent acceptance-review checks for source and input binding."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cli.lib import acceptance


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_changed_ignored_configuration_invalidates_acceptance_reuse(
    tmp_path: Path,
) -> None:
    """A gate result must not survive changes to configuration it can consume."""
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Acceptance Review")
    _git(tmp_path, "config", "user.email", "review@example.invalid")
    (tmp_path / ".gitignore").write_text(".env.local\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("FEATURE_FLAG=before\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "app.py")
    _git(tmp_path, "commit", "-qm", "initial")
    calls: list[list[str]] = []

    def successful_runner(command: list[str], _cwd: Path):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    first = acceptance.accept_revision(
        tmp_path,
        sha="HEAD",
        runner=successful_runner,
    )
    (tmp_path / ".env.local").write_text("FEATURE_FLAG=after\n", encoding="utf-8")
    second = acceptance.accept_revision(
        tmp_path,
        sha="HEAD",
        runner=successful_runner,
    )

    assert second["acceptance_id"] != first["acceptance_id"]
    assert second["reused"] is False
    assert calls == [["st", "check", "--check"], ["st", "check", "--check"]]


def test_local_configuration_change_during_gate_blocks_receipt(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Acceptance Review")
    _git(tmp_path, "config", "user.email", "review@example.invalid")
    (tmp_path / ".gitignore").write_text(".env.local\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    local_env = tmp_path / ".env.local"
    local_env.write_text("DATABASE_URL=before\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "app.py")
    _git(tmp_path, "commit", "-qm", "initial")

    def mutate(command: list[str], _cwd: Path):
        local_env.write_text("DATABASE_URL=after\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    with pytest.raises(
        acceptance.AcceptanceError,
        match="source_changed_during_acceptance",
    ):
        acceptance.accept_revision(tmp_path, sha="HEAD", runner=mutate)


def test_stale_receipt_rejects_changed_local_configuration(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Acceptance Review")
    _git(tmp_path, "config", "user.email", "review@example.invalid")
    (tmp_path / ".gitignore").write_text(".env.local\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    local_env = tmp_path / ".env.local"
    secret_before = "DATABASE_URL=postgresql://user:do-not-record@localhost/one\n"
    secret_after = "DATABASE_URL=postgresql://user:also-private@localhost/two\n"
    local_env.write_text(secret_before, encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "app.py")
    _git(tmp_path, "commit", "-qm", "initial")
    receipt = acceptance.accept_revision(
        tmp_path,
        sha="HEAD",
        runner=lambda command, _cwd: subprocess.CompletedProcess(command, 0, "ok", ""),
    )

    assert secret_before.strip() not in repr(receipt)
    local_env.write_text(secret_after, encoding="utf-8")

    with pytest.raises(
        acceptance.AcceptanceError,
        match="local environment/configuration inputs no longer match",
    ):
        acceptance.validate_acceptance_receipt(tmp_path, receipt, sha="HEAD")


def test_selected_gate_environment_change_invalidates_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Acceptance Review")
    _git(tmp_path, "config", "user.email", "review@example.invalid")
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "initial")
    secret = "postgresql://user:private-password@localhost/test"
    monkeypatch.setenv("TEST_DATABASE_URL", secret)
    receipt = acceptance.accept_revision(
        tmp_path,
        sha="HEAD",
        runner=lambda command, _cwd: subprocess.CompletedProcess(command, 0, "ok", ""),
    )

    assert secret not in repr(receipt)
    monkeypatch.setenv("TEST_DATABASE_URL", f"{secret}_changed")

    with pytest.raises(
        acceptance.AcceptanceError,
        match="local environment/configuration inputs no longer match",
    ):
        acceptance.validate_acceptance_receipt(tmp_path, receipt, sha="HEAD")


@pytest.mark.parametrize(("gate_path", "foreign_content"), [
    ("backend/cli/main.py", "UNRELATED_GATE = True\n"),
    ("backend/cli/commands/check.py", "UNRELATED_GATE = True\n"),
    ("scripts/lib/tool-registry.json", '{"tools": [{"name": "pytest", "check": {"binary": "foreign-gate"}}]}\n'),
])
def test_isolated_receipt_keeps_selected_cli_identity_with_unrelated_dirty_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_path: str,
    foreign_content: str,
) -> None:
    from cli import tool_registry

    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Acceptance Review")
    _git(tmp_path, "config", "user.email", "review@example.invalid")
    for relative in (
        "backend/cli/main.py", "backend/cli/commands/check.py",
        "backend/cli/lib/acceptance.py", "backend/cli/tool_registry.py",
        "backend/cli/commands/done_task_acceptance.py",
        "backend/app/utils/heavy_work.py", "backend/app/utils/safe_subprocess.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("SELECTED_GATE = True\n")
        path.chmod(0o644)
    registry = tmp_path / "scripts" / "lib" / "tool-registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"tools": []}\n')
    registry.chmod(0o644)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "selected gate")
    sha = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.setattr(acceptance, "__file__", str(tmp_path / "backend/cli/lib/acceptance.py"))
    monkeypatch.setattr(tool_registry, "tool_registry_path", lambda: registry)
    receipt = acceptance.accept_revision(
        tmp_path,
        sha=sha,
        execution_basis="isolated",
        runner=lambda command, _cwd: subprocess.CompletedProcess(command, 0, "ok", ""),
    )
    (tmp_path / gate_path).write_text(foreign_content)
    index = (tmp_path / ".git" / "index").read_bytes()

    validated = acceptance.validate_acceptance_receipt(tmp_path, receipt, sha=sha)

    assert validated["state"] == "success" and validated["acceptance_id"] == receipt["acceptance_id"]
    assert (tmp_path / gate_path).read_text() == foreign_content
    assert (tmp_path / ".git" / "index").read_bytes() == index
    assert _git(tmp_path, "rev-parse", "HEAD") == sha
