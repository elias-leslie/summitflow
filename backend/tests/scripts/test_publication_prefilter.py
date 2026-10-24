"""The PreToolUse guard's pure-shell prefilter may skip Python only when the
full policy (and the degraded fallback) would allow the call.

Every string literal in the guard test suites is replayed as a command: any
the policy denies must reach Python, so a policy fixture added later is
covered without touching this file.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from app.services.publication_hook import evaluate_payload

REPO = Path(__file__).resolve().parents[3]
PREFILTER = REPO / "scripts/lib/publication-prefilter.sh"
HOOK = REPO / "scripts/lib/publication-pretool-hook"
TESTS = REPO / "backend/tests"
FIXTURE_SOURCES = [
    TESTS / "services/test_irreversible_hook_guard.py",
    TESTS / "services/test_publication_guards.py",
    TESTS / "scripts/test_publication_guard_runtime.py",
]
QUIET = {"PATH": "/usr/bin:/bin", "SUMMITFLOW_JOURNAL_ALERTS": "0"}
SHARED = "/srv/workspaces/projects/summitflow"


def _payload(command: str, **extra: object) -> dict:
    return {"session_id": "s", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": command}, "cwd": SHARED, **extra}


def _skips(payloads: list[str]) -> list[bool]:
    """Run the prefilter over raw payload texts in one bash process."""
    driver = (f'source "{PREFILTER}"; while IFS= read -r -d "" p; do '
              'publication_prefilter_skip "$p" && echo 1 || echo 0; done')
    result = subprocess.run(["bash", "-c", driver], input="\0".join(payloads) + "\0", text=True,
                            capture_output=True, check=True, timeout=60, env=QUIET)
    decisions = result.stdout.split()
    assert len(decisions) == len(payloads)
    return [decision == "1" for decision in decisions]


def _fallback():
    spec = importlib.util.spec_from_file_location("publication_guard_entry",
                                                  REPO / "scripts/lib/publication_guard_entry.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.fallback_decision


def _denied(payload: dict, fallback) -> bool:
    try:
        blocked = evaluate_payload(payload).blocked
    except ValueError:
        blocked = True
    return blocked or fallback(payload) is not None


def _fixture_commands() -> list[str]:
    commands: set[str] = set()
    for source in FIXTURE_SOURCES:
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip():
                commands.add(node.value)
    return sorted(commands)


def test_every_denied_guard_fixture_reaches_python() -> None:
    fallback = _fallback()
    commands = _fixture_commands()
    payloads = [_payload(command) for command in commands]
    denied = [(command, payload) for command, payload in zip(commands, payloads, strict=True)
              if _denied(payload, fallback)]
    assert len(denied) > 150  # the fixture sources really were read
    skipped = _skips([json.dumps(payload) for _command, payload in denied])
    assert [command for (command, _), skip in zip(denied, skipped, strict=True) if skip] == []


EVASIONS = [
    "\\rm -rf /", "r''m -rf /", '"git" push origin main', "g\\it push", "ls\nrm -rf /", "ls\trm -rf ~",
    "GIT push origin main", "sudo -u root /usr/bin/git push", "$'\\x72m' -rf /", "x=$(git push)",
    "echo `git push`", "bash <<'EOF'\ngit push\nEOF", "eval \"$X\"", "find / -delete",
    "find /srv/workspaces -exec rm {} +", "ssh host 'qm destroy 101'", "mkfs.ext4 /dev/sdb",
    "codex --disable-hoo" + chr(0x212A),
    "git commit --no-verify -m x", "curl -X POST https://api.github.com/repos/o/r/releases",
    "echo cm0gLXJmIC8= | base64 -d | bash", "zpool destroy tank", "pvesh delete /nodes/x",
]


@pytest.mark.parametrize("command", EVASIONS)
def test_spelled_out_policy_terms_reach_python(command: str) -> None:
    assert _skips([json.dumps(_payload(command))]) == [False]
    assert _skips([json.dumps(_payload(command), ensure_ascii=True)]) == [False]


@pytest.mark.parametrize("raw", [
    json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "x": {"command": "git push"}}),
    json.dumps({"tool_name": "Bash", "x": {"command": "ls"}, "tool_input": {"command": "git push"}}),
    json.dumps({"tool_name": "Bash", "tool_input": {"cmd": "git push", "command": "ls"}}),
    json.dumps({"tool_name": "Bash", "tool_input": {"command": ["ls"]}}),
    json.dumps({"tool_name": "Bash", "tool_input": {"command": "  "}}),
    json.dumps({"tool_name": "Bash", "command": "ls"}),
    json.dumps({"tool_name": "exec_command", "tool_input": {"command": "ls"}}),
    json.dumps({"tool_name": "mcp__github__merge_pull_request", "tool_input": {}}),
    json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls é"}}, ensure_ascii=True),
    "", "not json",
])
def test_unusual_payloads_reach_python(raw: str) -> None:
    assert _skips([raw]) == [False]


COMMON = [
    "ls -la", "st check --quick --changed-only", "st commit -m 'x' --paths a", "uv sync --locked",
    "cat README.md | head -20", "pytest -q", "pnpm install --offline", "rg -n foo backend",
    "echo done && sleep 1", "st context task-1", "python3 -c 'print(1)'",
]


def test_common_commands_skip_python_and_policy_allows_them() -> None:
    fallback = _fallback()
    assert _skips([json.dumps(_payload(command)) for command in COMMON]) == [True] * len(COMMON)
    assert not any(_denied(_payload(command), fallback) for command in COMMON)


def test_hook_skips_guard_only_on_prefilter_allow(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / "scripts/lib").mkdir(parents=True)
    for name in ("publication-pretool-hook", "publication-prefilter.sh", "publication_guard_entry.py"):
        (root / "scripts/lib" / name).write_text((REPO / "scripts/lib" / name).read_text())
    marker = tmp_path / "guard-ran"
    guard = root / "scripts/lib/command-guard"
    guard.write_text(f"#!/bin/sh\ncat > {marker}\necho GUARD\n")
    guard.chmod(0o755)

    def run(command: str) -> str:
        return subprocess.run(["bash", str(root / "scripts/lib/publication-pretool-hook")],
                              input=json.dumps(_payload(command)), text=True, capture_output=True,
                              check=True, timeout=10, env=QUIET).stdout.strip()

    assert run("ls -la") == "{}"
    assert not marker.exists()
    assert run("git push origin main") == "GUARD"
    assert json.loads(marker.read_text())["tool_input"]["command"] == "git push origin main"
    (root / "scripts/lib/publication-prefilter.sh").unlink()
    assert run("ls -la") == "GUARD"
    (root / "scripts/lib/publication-prefilter.sh").write_text(PREFILTER.read_text())
    (root / "scripts/lib/publication_guard_entry.py").unlink()
    assert run("ls -la") == "GUARD"


def test_live_hook_still_denies_through_prefilter(tmp_path: Path) -> None:
    result = subprocess.run(["bash", str(HOOK)], input=json.dumps(_payload("\\rm -rf /")), text=True,
                            capture_output=True, check=True, timeout=10,
                            env={**QUIET, "HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")})
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_large_escape_heavy_payload_reaches_python_well_inside_hook_timeout(tmp_path: Path) -> None:
    """Bash regex backtracking on a huge payload must never push the hook past its 5 s timeout."""
    heredoc = "cat <<'EOF'\n" + '"x\n' * 120_000 + "EOF\n"
    assert _skips([json.dumps(_payload(heredoc + "ls"))]) == [False]
    result = subprocess.run(["bash", str(HOOK)], input=json.dumps(_payload(heredoc + "&& git push origin main")),
                            text=True, capture_output=True, check=True, timeout=4,
                            env={**QUIET, "HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")})
    assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
