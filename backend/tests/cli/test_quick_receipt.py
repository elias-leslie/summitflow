"""A passing quick check is reused only for the same files, config and HEAD."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli.commands import check_dispatch
from cli.lib import quick_receipt


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (tmp_path / "a.py").write_text("a = 1\n")
    (tmp_path / "b.py").write_text("b = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "initial")
    monkeypatch.setattr(quick_receipt, "_receipt_local_inputs", lambda _repo: {"fixed": True})
    monkeypatch.setenv("ST_QUICK_RECEIPTS", "1")
    return tmp_path


def _pass(repo: Path, files: list[str]) -> None:
    before = quick_receipt.scope_hashes(repo, files)
    assert quick_receipt.record(repo, files, before, quick_receipt.context_hash(repo))


def test_unchanged_files_reuse_the_passing_result(repo: Path) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    assert quick_receipt.reusable(repo, ["a.py"]) is not None


def test_nothing_is_reused_without_a_receipt_or_files(repo: Path) -> None:
    assert quick_receipt.reusable(repo, ["a.py"]) is None
    _pass(repo, ["a.py"])
    assert quick_receipt.reusable(repo, []) is None


def test_edited_file_is_checked_again(repo: Path) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    (repo / "a.py").write_text("a = 3\n")
    assert quick_receipt.reusable(repo, ["a.py"]) is None


def test_file_added_or_deleted_since_is_checked_again(repo: Path) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    assert quick_receipt.reusable(repo, ["a.py", "b.py"]) is None
    (repo / "a.py").unlink()
    assert quick_receipt.reusable(repo, ["a.py"]) is None


def test_a_subset_of_a_passing_scope_is_reused_but_not_a_superset(repo: Path) -> None:
    (repo / "a.py").write_text("a = 2\n")
    (repo / "b.py").write_text("b = 2\n")
    _pass(repo, ["a.py", "b.py"])
    assert quick_receipt.reusable(repo, ["b.py"]) is not None
    (repo / "c.py").write_text("c = 1\n")
    assert quick_receipt.reusable(repo, ["a.py", "c.py"]) is None


def test_changed_gate_config_or_head_is_checked_again(repo: Path) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 80\n")
    assert quick_receipt.reusable(repo, ["a.py"]) is None
    (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert quick_receipt.reusable(repo, ["a.py"]) is not None
    _git(repo, "commit", "-q", "--allow-empty", "-m", "other work")
    assert quick_receipt.reusable(repo, ["a.py"]) is None


def test_changed_gate_environment_is_checked_again(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    monkeypatch.setattr(quick_receipt, "_receipt_local_inputs", lambda _repo: {"fixed": False})
    assert quick_receipt.reusable(repo, ["a.py"]) is None


def test_expired_receipt_is_checked_again(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    monkeypatch.setenv("ST_QUICK_REUSE_SECONDS", "10")
    receipt = quick_receipt.reusable(repo, ["a.py"])
    assert receipt is not None
    assert quick_receipt.reusable(repo, ["a.py"], now=float(receipt["at"]) + 11) is None


def test_a_run_during_which_a_file_changed_leaves_no_receipt(repo: Path) -> None:
    (repo / "a.py").write_text("a = 2\n")
    before = quick_receipt.scope_hashes(repo, ["a.py"])
    context = quick_receipt.context_hash(repo)
    (repo / "a.py").write_text("a = 3\n")
    assert not quick_receipt.record(repo, ["a.py"], before, context)
    assert quick_receipt.reusable(repo, ["a.py"]) is None


def _runtime(repo: Path, runs: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        resolve_repo_root=lambda: repo,
        changed_files=lambda _root: ["a.py"],
        tool_selections={"--quick": (("ruff",), False)},
    )


def _quick(monkeypatch: pytest.MonkeyPatch, repo: Path, code: int, *extra: str) -> tuple[int, list[str]]:
    runs: list[str] = []

    def fake_run(*_args: object, **_kwargs: object) -> int:
        runs.append("ran")
        return code

    monkeypatch.setattr(check_dispatch, "run_selected", fake_run)
    ctx = SimpleNamespace(args=["--quick", "--changed-only", *extra])
    status = check_dispatch.handle_check_args(ctx, {"ruff": {}}, runtime=_runtime(repo, runs))  # type: ignore[arg-type]
    return status, runs


def test_quick_check_runs_once_for_unchanged_files(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "a.py").write_text("a = 2\n")
    assert _quick(monkeypatch, repo, 0) == (0, ["ran"])
    assert _quick(monkeypatch, repo, 0) == (0, [])
    assert "CHECK:REUSED:quick" in capsys.readouterr().out
    assert _quick(monkeypatch, repo, 0, "--no-reuse") == (0, ["ran"])
    (repo / "a.py").write_text("a = 3\n")
    assert _quick(monkeypatch, repo, 0) == (0, ["ran"])


def test_failed_quick_check_is_never_reused(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "a.py").write_text("a = 2\n")
    assert _quick(monkeypatch, repo, 1) == (1, ["ran"])
    assert _quick(monkeypatch, repo, 1) == (1, ["ran"])


def test_receipts_can_be_switched_off(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / "a.py").write_text("a = 2\n")
    _pass(repo, ["a.py"])
    monkeypatch.setenv("ST_QUICK_RECEIPTS", "0")
    assert quick_receipt.reusable(repo, ["a.py"]) is None
    assert not quick_receipt.record(repo, ["a.py"], quick_receipt.scope_hashes(repo, ["a.py"]), "ctx")
