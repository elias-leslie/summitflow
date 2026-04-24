from __future__ import annotations

from pathlib import Path

import pytest

from app.services.command_guard import (
    evaluate_shell_command,
    get_bash_intercept_words,
    staged_destructive_decision,
)
from app.services.destructive_path_guard import GuardConflict, GuardDecision


def _blocked_decision(repo_root: Path, path: str) -> GuardDecision:
    return GuardDecision(
        blocked=True,
        project_id="summitflow",
        repo_root=str(repo_root),
        current_session_id="sess-self",
        destructive_paths=(path,),
        conflicts=(
            GuardConflict(
                session_id="sess-foreign",
                task_id=None,
                branch="main",
                working_dir=str(repo_root),
                reason="unknown_scope",
                paths=(path,),
            ),
        ),
    )


def test_registry_redirects_raw_pytest(tmp_path: Path) -> None:
    decision = evaluate_shell_command("pytest backend/tests/", tmp_path)

    assert decision.blocked is True
    assert decision.code == "redirect"
    assert "st check pytest" in (decision.message or "")


def test_wrapper_commands_are_allowed(tmp_path: Path) -> None:
    decision = evaluate_shell_command("dt pytest backend/tests/", tmp_path)

    assert decision.blocked is False


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rebuild.sh summitflow", "st service"),
        ("commit.sh --current", "st git commit"),
        ("sf-browser health", "st browser"),
        ("web-research search --query SummitFlow", "st web"),
        ("proxmox-vm.sh list", "st vm"),
        ("restore.sh --list", "st backup"),
        ("setup-services.sh --help", "st setup"),
    ],
)
def test_redirects_legacy_operator_wrappers(command: str, expected: str, tmp_path: Path) -> None:
    decision = evaluate_shell_command(command, tmp_path)

    assert decision.blocked is True
    assert decision.code == "redirect"
    assert expected in (decision.message or "")


def test_allows_raw_docker_run(tmp_path: Path) -> None:
    decision = evaluate_shell_command("docker run --rm postgres:16", tmp_path)

    assert decision.blocked is False


def test_redirects_docker_compose_to_st_docker(tmp_path: Path) -> None:
    decision = evaluate_shell_command("docker compose up -d", tmp_path)

    assert decision.blocked is True
    assert decision.code == "redirect"
    assert "st docker" in (decision.message or "")


def test_blocks_raw_git_commit(tmp_path: Path) -> None:
    decision = evaluate_shell_command("git commit -m 'test'", tmp_path)

    assert decision.blocked is True
    assert decision.code == "git_commit_redirect"
    assert "st git commit --push" in (decision.message or "")


def test_blocks_nested_shell_git_reset(tmp_path: Path) -> None:
    decision = evaluate_shell_command("bash -lc 'git reset --hard'", tmp_path)

    assert decision.blocked is True
    assert decision.code == "git_reset_hard"


def test_blocks_git_clean_fd(tmp_path: Path) -> None:
    decision = evaluate_shell_command("git clean -fd", tmp_path)

    assert decision.blocked is True
    assert decision.code == "git_clean_fd"


def test_blocks_git_restore_on_foreign_owned_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = "docs/plans/vantage-rollout-plan.md"

    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr(
        "app.services.command_guard.check_destructive_paths",
        lambda root, paths: _blocked_decision(repo_root, target),
    )

    decision = evaluate_shell_command(f"git restore {target}", repo_root)

    assert decision.blocked is True
    assert decision.code == "ownership_conflict"
    assert "Refusing destructive path action" in (decision.message or "")


def test_allows_git_restore_staged_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)

    decision = evaluate_shell_command("git restore --staged docs/plans/vantage-rollout-plan.md", repo_root)

    assert decision.blocked is False


def test_blocks_git_checkout_all_in_managed_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr(
        "app.services._command_guard_helpers.get_managed_repos",
        lambda: [repo_root.resolve()],
    )

    decision = evaluate_shell_command("git checkout .", repo_root)

    assert decision.blocked is True
    assert decision.code == "git_checkout_all"


def test_allows_git_checkout_all_in_unmanaged_temp_clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "temp-clone"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr("app.services._command_guard_helpers.get_managed_repos", lambda: [])

    decision = evaluate_shell_command("git checkout .", repo_root)

    assert decision.blocked is False


def test_blocks_git_restore_all_in_managed_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr(
        "app.services._command_guard_helpers.get_managed_repos",
        lambda: [repo_root.resolve()],
    )

    decision = evaluate_shell_command("git restore .", repo_root)

    assert decision.blocked is True
    assert decision.code == "git_restore_all"


def test_allows_git_restore_all_in_unmanaged_temp_clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "temp-clone"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr("app.services._command_guard_helpers.get_managed_repos", lambda: [])

    decision = evaluate_shell_command("git restore .", repo_root)

    assert decision.blocked is False


def test_blocks_git_revert_path_overlap(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = "docs/plans/vantage-rollout-plan.md"

    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr("app.services._command_guard_helpers.git_revert_paths", lambda root, args, error_class: [target])
    monkeypatch.setattr(
        "app.services.command_guard.check_destructive_paths",
        lambda root, paths: _blocked_decision(repo_root, target),
    )

    decision = evaluate_shell_command("git revert --no-edit e4f23efc7", repo_root)

    assert decision.blocked is True
    assert decision.code == "ownership_conflict"


def test_blocks_git_rm_on_foreign_owned_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = "docs/plans/vantage-rollout-plan.md"

    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr(
        "app.services.command_guard.check_destructive_paths",
        lambda root, paths: _blocked_decision(repo_root, target),
    )

    decision = evaluate_shell_command(f"git rm -- {target}", repo_root)

    assert decision.blocked is True
    assert decision.code == "ownership_conflict"


def test_staged_destructive_decision_blocks_on_foreign_owned_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = "docs/plans/vantage-rollout-plan.md"

    monkeypatch.setattr("app.services.command_guard.staged_destructive_paths", lambda root: [target])
    monkeypatch.setattr(
        "app.services.command_guard.check_destructive_paths",
        lambda root, paths: _blocked_decision(repo_root, target),
    )

    decision = staged_destructive_decision(repo_root)

    assert decision.blocked is True
    assert decision.code == "ownership_conflict"


def test_intercept_words_cover_shell_wrappers() -> None:
    words = get_bash_intercept_words()

    assert "git" in words
    assert "env" in words
    assert "bash" in words
