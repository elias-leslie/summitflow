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


@pytest.mark.parametrize(
    "command",
    [
        "/repo/backend/.venv/bin/pytest tests/workflows/test_pipeline.py -v",
        "/repo/backend/.venv/bin/python -m pytest tests/workflows/test_pipeline.py -v",
        "cd /repo/backend && /repo/backend/.venv/bin/python -m pytest tests/workflows/test_pipeline.py",
    ],
)
def test_registry_redirects_absolute_venv_pytest(command: str, tmp_path: Path) -> None:
    decision = evaluate_shell_command(command, tmp_path)

    assert decision.blocked is True
    assert decision.code == "redirect"
    assert "st check pytest" in (decision.message or "")


def test_st_check_commands_are_allowed(tmp_path: Path) -> None:
    decision = evaluate_shell_command("st check pytest -- backend/tests/", tmp_path)

    assert decision.blocked is False


def test_intercepts_raw_jj() -> None:
    assert "jj" in get_bash_intercept_words()


@pytest.mark.parametrize(
    "command",
    [
        "Xorg :99 -noreset -nolisten tcp -ac",
        "/usr/lib/xorg/Xorg :99 -noreset -nolisten tcp -ac",
        "sudo -n /usr/lib/xorg/Xorg :99 -noreset -nolisten tcp -ac "
        "-config /srv/workspaces/projects/the-aftertimes/.dev-tools/agent_runs/"
        "2026-07-13-overworld-redesign-performance-final-5d06cb83/xorg-amd.conf",
        "env -u DISPLAY sudo -n /usr/lib/xorg/Xorg :99 -noreset -nolisten tcp -ac "
        "-config /tmp/xorg-amd.conf",
        "nohup env -u DISPLAY sudo -n /usr/lib/xorg/Xorg :99 -noreset "
        "-nolisten tcp -ac -config /tmp/xorg-amd.conf >/tmp/xorg.log 2>&1 &",
        "bash -lc 'env -u DISPLAY sudo -n /usr/lib/xorg/Xorg :99 -noreset "
        "-nolisten tcp -ac -config /tmp/xorg-amd.conf'",
        "Xorg.wrap :99 -noreset -nolisten tcp -ac",
        "X :99 -noreset -nolisten tcp -ac",
        "/usr/bin/X :99 -noreset -nolisten tcp -ac",
        "/usr/lib/xorg/Xorg.bin :99 -noreset -nolisten tcp -ac",
        "XORG.BIN :99 -noreset -nolisten tcp -ac",
        "/usr/bin/xinit /tmp/xinitrc -- /usr/bin/X :99",
        "bash -lc 'STARTX -- :99'",
        "nohup env -u DISPLAY sudo -n /usr/bin/startx -- :99 "
        ">/tmp/startx.log 2>&1 &",
        "NoHuP EnV -u DISPLAY SuDo -n /usr/bin/X :99 -noreset -nolisten tcp",
    ],
)
def test_blocks_direct_xorg_launches(command: str, tmp_path: Path) -> None:
    decision = evaluate_shell_command(command, tmp_path)

    assert decision.blocked is True
    assert decision.code == "dangerous"
    assert "isolated Proxmox VM" in (decision.message or "")


@pytest.mark.parametrize(
    "command",
    [
        "sudo -n Xvfb :99 -screen 0 1280x720x24 -nolisten tcp",
        "env -u DISPLAY sudo -n /usr/bin/Xvfb :99 -screen 0 1280x720x24",
        "nohup sudo -- xvfb-run -a game-test >/tmp/game-test.log 2>&1 &",
        "sudo -n bash -lc '/usr/bin/Xvfb :99 -screen 0 1280x720x24'",
    ],
)
def test_blocks_privileged_xvfb_launches(command: str, tmp_path: Path) -> None:
    decision = evaluate_shell_command(command, tmp_path)

    assert decision.blocked is True
    assert decision.code == "dangerous"
    assert "Do not run Xvfb or xvfb-run through sudo/root" in (decision.message or "")


@pytest.mark.parametrize(
    "command",
    [
        "Xvfb :99 -screen 0 1280x720x24 -nolisten tcp",
        "env -u DISPLAY /usr/bin/Xvfb :99 -screen 0 1280x720x24 -nolisten tcp",
        "xvfb-run -a -s '-screen 0 1280x720x24 -nolisten tcp' game-test",
        "env -u DISPLAY xvfb-run -a game-test",
    ],
)
def test_allows_unprivileged_xvfb_launches(command: str, tmp_path: Path) -> None:
    decision = evaluate_shell_command(command, tmp_path)

    assert decision.blocked is False


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rebuild.sh summitflow", "st service"),
        ("commit.sh --current", "st commit"),
        ("dt pytest backend/tests/", "st check"),
        ("db tables", "st db"),
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
    assert "st commit --push" in (decision.message or "")


@pytest.mark.parametrize(
    ("command", "code", "expected"),
    [
        ("git status --short", "git_status_redirect", "st jj status"),
        ("git diff --stat", "git_diff_redirect", "st jj diff"),
        ("git -C repo log -1", "git_log_redirect", "st jj log"),
        ("git fetch origin", "git_fetch_redirect", "st vcs reconcile"),
        ("git pull --ff-only", "git_pull_redirect", "st vcs reconcile"),
        ("git push origin main", "git_push_redirect", "st commit --push"),
    ],
)
def test_redirects_raw_git_vcs_in_managed_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    code: str,
    expected: str,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr(
        "app.services._command_guard_helpers.get_managed_repos",
        lambda: [repo_root.resolve()],
    )

    decision = evaluate_shell_command(command, tmp_path)

    assert decision.blocked is True
    assert decision.code == code
    assert expected in (decision.message or "")


def test_allows_raw_git_status_in_unmanaged_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: tmp_path)
    monkeypatch.setattr("app.services._command_guard_helpers.get_managed_repos", lambda: [])

    decision = evaluate_shell_command("git status --short", tmp_path)

    assert decision.blocked is False


def test_redirects_raw_jj_in_managed_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr("app.services.command_guard._repo_root", lambda cwd: repo_root)
    monkeypatch.setattr(
        "app.services._command_guard_helpers.get_managed_repos",
        lambda: [repo_root.resolve()],
    )

    decision = evaluate_shell_command("jj status", repo_root)

    assert decision.blocked is True
    assert decision.code == "jj_redirect"
    assert "st jj" in (decision.message or "")


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


def test_blocks_st_done_for_different_agent_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_HUB_SESSION_ID", "sess-current")
    monkeypatch.setattr(
        "app.services.command_guard._agent_hub_task_id_for_session",
        lambda session_id: "task-current",
    )

    decision = evaluate_shell_command("st -P agent-hub done task-other --skip-diff-gate", tmp_path)

    assert decision.blocked is True
    assert decision.code == "st_done_task_mismatch"
    assert "owns task-current" in (decision.message or "")
    assert "not task-other" in (decision.message or "")


def test_blocks_st_done_task_option_for_different_agent_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_HUB_SESSION_ID", "sess-current")
    monkeypatch.setattr(
        "app.services.command_guard._agent_hub_task_id_for_session",
        lambda session_id: "task-current",
    )

    decision = evaluate_shell_command("st done 1.2 --task task-other -m done", tmp_path)

    assert decision.blocked is True
    assert decision.code == "st_done_task_mismatch"


def test_allows_st_done_for_current_agent_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_HUB_SESSION_ID", "sess-current")
    monkeypatch.setattr(
        "app.services.command_guard._agent_hub_task_id_for_session",
        lambda session_id: "task-current",
    )

    decision = evaluate_shell_command("st done task-current --skip-diff-gate", tmp_path)

    assert decision.blocked is False


def test_allows_st_done_without_agent_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("AGENT_HUB_SESSION_ID", raising=False)
    monkeypatch.delenv("AGENT_HUB_EXTERNAL_ID", raising=False)
    monkeypatch.delenv("AGENT_HUB_TASK_ID", raising=False)

    decision = evaluate_shell_command("st done task-other --skip-diff-gate", tmp_path)

    assert decision.blocked is False


def test_blocks_nested_st_done_for_different_agent_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_HUB_EXTERNAL_ID", "task-current")

    decision = evaluate_shell_command("bash -lc 'st done task-other --skip-diff-gate'", tmp_path)

    assert decision.blocked is True
    assert decision.code == "st_done_task_mismatch"


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
    assert "sudo" in words
    assert "X" in words
    assert "Xorg" in words
    assert "Xorg.bin" in words
    assert "Xvfb" in words
    assert "xinit" in words
    assert "startx" in words
    assert "bash" in words
    assert "st" in words
