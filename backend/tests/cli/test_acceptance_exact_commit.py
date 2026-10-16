"""Exact-commit acceptance: shared receipt lookup, isolated slot, basis selection."""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from cli.commands import done_task_acceptance
from cli.lib import acceptance, acceptance_coordinator


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, local_gate_tools: None) -> Path:
    git(tmp_path, "init", "-q", "--initial-branch=main")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "app.py").write_text("value = 1\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial")
    return tmp_path


def passing(calls: list[list[str]]):
    def run(command: list[str], cwd: Path):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "RUFF:OK:0", "")

    return run


def test_repo_lock_waits_as_long_as_st_commit() -> None:
    assert acceptance.REPO_LOCK_WAIT_SECONDS == 300.0


def test_commit_index_finds_a_receipt_older_than_the_recent_scan_window(repo: Path) -> None:
    calls: list[list[str]] = []
    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=passing(calls))
    directory = acceptance.acceptance_artifact_directory(repo)
    # Only the immutable receipt and the commit index remain; many newer
    # receipts for other work push it out of the mtime scan.
    for path in directory.glob("*.json"):
        if path.stem != accepted["acceptance_id"]:
            path.unlink()
    for number in range(acceptance._RECEIPT_SCAN_LIMIT + 4):
        (directory / f"{number:064x}.json").write_text(json.dumps({"source": {"commit": "other"}}))
    (repo / "unrelated.py").write_text("another agent's work\n")

    reused = acceptance.accept_revision(repo, sha="HEAD", runner=passing(calls))

    assert reused["acceptance_id"] == accepted["acceptance_id"] and reused["reused"] is True
    assert len(calls) == 1
    index = json.loads((directory / "commits" / f"{git(repo, 'rev-parse', 'HEAD')}.json").read_text())
    assert index["receipts"][0] == accepted["acceptance_id"]


def test_task_request_reuses_full_proof_for_the_same_commit(repo: Path) -> None:
    calls: list[list[str]] = []
    full = acceptance.accept_revision(repo, sha="HEAD", runner=passing(calls))

    result = acceptance_coordinator.accept_source(repo, sha=git(repo, "rev-parse", "HEAD"), materialization="actual",
                                                  coverage="task", scope=("app.py",), runner=passing(calls))

    assert result.reused is True
    assert result.reference.coverage == "full"
    assert result.reference.acceptance_id == full["acceptance_id"]
    assert calls == [["st", "check", "--check"]]


def test_full_proof_stands_in_for_task_proof_only_when_required_stages_passed() -> None:
    receipt = {"checks": [{"evidence": {"stages": [
        {"id": "python", "state": "pass", "coverage": "full"},
        {"id": "fleet", "state": "not-applicable", "coverage": "focused"},
    ]}}]}
    assert acceptance._full_receipt_covers(receipt, ())
    assert acceptance._full_receipt_covers(receipt, ("python",))
    assert not acceptance._full_receipt_covers(receipt, ("python", "fleet"))
    assert not acceptance._full_receipt_covers({"checks": []}, ("python",))


def test_task_receipt_for_another_scope_is_not_borrowed(repo: Path) -> None:
    calls: list[list[str]] = []
    (repo / "other.py").write_text("x = 1\n")
    git(repo, "add", "other.py")
    git(repo, "commit", "-qm", "other")
    acceptance.accept_revision(repo, sha="HEAD", coverage="task", scope=("app.py",), runner=passing(calls))
    (repo / "unrelated.py").write_text("wip\n")
    head = git(repo, "rev-parse", "HEAD")

    assert acceptance.receipt_for_commit(repo, head, "task", scope=("other.py",)) is None
    assert acceptance.receipt_for_commit(repo, head, "task", scope=("app.py",)) is not None
    assert acceptance.receipt_for_commit(repo, head, "full") is None


def test_isolated_basis_takes_no_guard_or_edit_freezing_op_lease(repo: Path, monkeypatch) -> None:
    from cli.lib import coord

    @contextmanager
    def forbidden(*_args, **_kwargs):
        pytest.fail("isolated acceptance must not freeze edits")
        yield

    monkeypatch.setattr(coord, "op_lease", forbidden)
    monkeypatch.setattr(coord, "guard", lambda *_args, **_kwargs: pytest.fail("isolated acceptance takes no guard"))
    monkeypatch.setattr(acceptance, "_accept_revision", lambda repo, **kwargs: {"basis": kwargs["execution_basis"]})

    assert acceptance.accept_revision(repo, sha="HEAD", execution_basis="isolated") == {"basis": "isolated"}
    with pytest.raises(pytest.fail.Exception):
        acceptance.accept_revision(repo, sha="HEAD")


def test_in_place_acceptance_still_refuses_a_dirty_checkout(repo: Path) -> None:
    (repo / "app.py").write_text("value = 2\n")
    with pytest.raises(acceptance.AcceptanceError, match="clean checkout"):
        acceptance.accept_revision(repo, sha="HEAD", runner=passing([]))


def test_acceptance_slot_serializes_runs_without_taking_the_repo_lock(repo: Path) -> None:
    with acceptance.acceptance_slot(repo, purpose="first"):
        with acceptance.repo_lock(repo, purpose="an edit-time commit"):
            pass
        with pytest.raises(acceptance.AcceptanceError, match="acceptance_slot_busy"), \
                acceptance.acceptance_slot(repo, purpose="second", wait_seconds=0):
            pass
    with acceptance.acceptance_slot(repo, purpose="after", wait_seconds=0):
        pass


def test_isolated_acceptance_reuses_any_basis_receipt_without_running(repo: Path, monkeypatch) -> None:
    accepted = acceptance.accept_revision(repo, sha="HEAD", runner=passing([]))
    (repo / "unrelated.py").write_text("another agent's work\n")
    monkeypatch.setattr(done_task_acceptance, "_run_isolated", lambda *a, **k: pytest.fail("receipt should be reused"))

    reused = done_task_acceptance.accept_isolated_revision(repo, sha="HEAD", scope=(), task_id="")

    assert reused["acceptance_id"] == accepted["acceptance_id"]
    assert reused["reused"] is True and reused["working_tree_clean"] is False


def test_isolated_waiter_reuses_the_receipt_the_slot_holder_wrote(repo: Path, monkeypatch) -> None:
    captures: list[bool] = []
    receipt = {"acceptance_id": "a", "reused": True}

    def capture(_repo, **_options):
        captures.append(True)
        return {}, {}, (receipt if len(captures) == 2 else None)

    monkeypatch.setattr(done_task_acceptance, "_capture_isolated", capture)
    monkeypatch.setattr(done_task_acceptance, "_run_isolated", lambda *a, **k: pytest.fail("holder's receipt reused"))

    assert done_task_acceptance.accept_isolated_revision(repo, sha="HEAD", scope=(), task_id="") is receipt
    assert len(captures) == 2


@pytest.mark.parametrize(("config", "project_id", "expected"), [
    (None, "summitflow", "isolated"),
    (None, "nightshift", "actual"),
    ('[acceptance]\nbasis = "isolated"\n', "nightshift", "isolated"),
    ('[acceptance]\nbasis = "in-place"\n', "summitflow", "actual"),
    ('[acceptance]\nhost_tools = ["docker"]\n', "summitflow", "isolated"),
])
def test_acceptance_basis_is_selected_per_project(tmp_path: Path, config: str | None, project_id: str,
                                                   expected: str) -> None:
    if config is not None:
        (tmp_path / ".st-check.toml").write_text(config)
    assert acceptance_coordinator.configured_materialization(tmp_path, project_id) == expected
    assert acceptance_coordinator.select_materialization(tmp_path, dirty=False, project_id=project_id) == expected
    assert acceptance_coordinator.select_materialization(tmp_path, dirty=True, project_id=project_id) == "isolated"


def test_unknown_acceptance_basis_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".st-check.toml").write_text('[acceptance]\nbasis = "sometimes"\n')
    with pytest.raises(acceptance.AcceptanceError, match="basis must be"):
        acceptance_coordinator.configured_materialization(tmp_path, "nightshift")
