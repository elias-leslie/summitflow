"""The live PreToolUse hook denies a small irreversible command set.

Regression: the destructive guard in command_guard had no live caller, so the
shared hook let ``git reset --hard``/``git clean -fd``/``rm -rf <project>``
through in checkouts shared by many agents.
"""

from __future__ import annotations

import io
import json

import pytest

from app.services import _publication_guard, publication_hook
from app.services._publication_guard import (
    evaluate_irreversible_command,
    evaluate_publication_command,
)
from app.services.command_guard import evaluate_shell_command

SHARED = "/srv/workspaces/projects/summitflow"

DENIED = [
    "git reset --hard", "git reset --hard HEAD~1", "cd backend && git reset --hard origin/main",
    "git -C /srv/workspaces/projects/summitflow reset --hard", "bash -lc 'git reset --hard'",
    "sudo git reset --hard", "git clean -fd", "git clean -f", "git clean -xdf", "git clean --force -d",
    "git checkout .", "git checkout -- .", "git checkout HEAD -- .", "git restore .",
    "git restore --worktree --source HEAD .", "git restore -- :/",
    "git stash", "git stash -u", "git stash push -m wip", "git stash save wip", "git stash drop", "git stash clear",
    "rm -rf /", "rm -rf ~", "rm -rf ~/", "rm -fr $HOME", "rm -rf /srv", "rm -rf /srv/workspaces",
    "rm -rf /srv/workspaces/projects/summitflow", "rm -r /srv/workspaces/projects/summitflow/",
    "rm -rf /srv/workspaces/projects/*", "cd /srv/workspaces/projects && rm -rf summitflow", "rm -rf .",
    "rm -rf /media/kasadis/Backups/davion-gem", "rm -rf /mnt/summitflow-native", "rm -Rf /etc",
    "/bin/rm -rf -- /home/kasadis", "echo $(git reset --hard)", "bash <<'EOF'\ngit reset --hard\nEOF",
    "cat <<'EOF' | sh\ngit clean -fd\nEOF", "ls && git stash && git pull",
]
ALLOWED = [
    "git status", "git diff", "git fetch", "git stash list", "git stash show -p", "git stash pop",
    "git restore --staged .", "git restore -- backend/app/x.py", "git checkout -- backend/app/x.py",
    "git checkout main", "git reset --soft HEAD~1", "git reset HEAD backend/x.py", "git clean -n -d",
    "git clean -nfd", "rm -rf build/", "rm -rf node_modules", "rm -f /srv/workspaces", "rm -rf $BUILD_DIR",
    "rm -rf /srv/workspaces/projects/summitflow/frontend/.next", "rm -rf /tmp/claude-1000/foo",
    "rm -rf /srv/workspaces/st-local-acceptance.hf9oW2",
    "git -C /tmp/scratch-repo reset --hard", "cd /tmp/x && git clean -fdx && git stash",
    # Soft redirects are advice elsewhere, never hook denies.
    "pytest backend/tests", "st check --quick --changed-only",
    # Quoted and heredoc data is not a command.
    "st commit -m 'never run git reset --hard or rm -rf /'",
    "git commit -m \"$(cat <<'EOF'\nStop git reset --hard and git clean -fd; rm -rf /srv\nEOF\n)\"",
    "cat > /tmp/notes.md <<'EOF'\ngit reset --hard\nrm -rf /\nEOF",
    "python3 - <<'EOF'\nprint('git stash drop')\nEOF", "echo 'git checkout .'", "rg 'git reset --hard' docs",
]


@pytest.fixture(autouse=True)
def _home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/kasadis")


@pytest.mark.parametrize("command", DENIED)
def test_irreversible_denied_in_shared_checkout(command: str) -> None:
    assert evaluate_irreversible_command(command, SHARED).blocked


@pytest.mark.parametrize("command", ALLOWED)
def test_ordinary_and_quoted_commands_allowed(command: str) -> None:
    assert not evaluate_irreversible_command(command, SHARED).blocked


@pytest.mark.parametrize("command", ["git reset --hard", "git checkout .", "git stash", "git clean -fdx"])
def test_disposable_checkout_is_exempt(command: str) -> None:
    assert not evaluate_irreversible_command(command, "/tmp/scratch-clone").blocked


def test_force_push_main_denied_everywhere() -> None:
    assert evaluate_irreversible_command("git push --force origin main", "/tmp/scratch-clone").blocked


def _run_hook(payload: dict, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> dict:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert publication_hook.publication_hook_main() == 0
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("payload", [
    {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}, "cwd": SHARED},
    {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "git clean -fd"]}, "cwd": SHARED},
    {"tool_name": "exec_command", "tool_input": {"cmd": "rm -rf /srv/workspaces"}, "cwd": "/tmp"},
])
def test_hook_emits_harness_deny(payload: dict, monkeypatch, capsys) -> None:
    output = _run_hook(payload, monkeypatch, capsys)["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert output["hookEventName"] == "PreToolUse"
    assert "\n" not in output["permissionDecisionReason"]


def test_hook_fails_open_on_irreversible_policy_error(monkeypatch, capsys) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("policy defect")

    monkeypatch.setattr(publication_hook, "evaluate_irreversible_command", boom)
    payload = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}, "cwd": SHARED}
    assert _run_hook(payload, monkeypatch, capsys) == {}
    assert _publication_guard.evaluate_irreversible_command is not boom


def test_commit_message_heredoc_mentioning_no_verify_allowed() -> None:
    command = "st commit -m \"$(cat <<'EOF'\nfix: document --no-verify misuse\nEOF\n)\""
    assert not evaluate_publication_command(command).blocked
    # A heredoc that a shell executes still counts.
    assert evaluate_publication_command("bash -c \"$(cat <<'EOF'\ngit commit --no-verify\nEOF\n)\"").blocked


def test_legacy_shell_guard_shares_protected_root_policy(tmp_path) -> None:
    decision = evaluate_shell_command("rm -rf /srv/workspaces/projects/summitflow", tmp_path)
    assert decision.blocked
    assert decision.code == "rm_protected_root"
