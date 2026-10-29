"""The per-call guard paths keep giving the decisions they gave when the corpus was recorded.

fixtures/guard_corpus.json holds ~980 commands (every fixture string of the guard
test suites, plus one or more commands per policy rule and allowed commands) with
the answers of the guard before its startup was made lazy. For each command the
real shell entry points are run and compared, reason text included:

- hook: scripts/lib/publication-pretool-hook, prefilter on and off (the prefilter
  may only skip Python for calls the policy allows, so both must agree);
- fallback: the same hook forced onto the degraded stdlib deny-list;
- shell: scripts/lib/command-guard --shell-command --json (Agent Hub's bash tool).

Editing a policy rule changes some answers on purpose: re-record the affected
entries by running the commands through the same entry points and writing the new
answers into the fixture in the same commit as the rule change.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "scripts/lib/publication-pretool-hook"
COMMAND_GUARD = REPO / "scripts/lib/command-guard"
CORPUS = json.loads((Path(__file__).parent / "fixtures/guard_corpus.json").read_text())
# The recording environment: a fixed home (home-relative deletions name it in
# their reason), no journal alerts, and a database URL that is never contacted
# (the shell guard's settings require one to be set).
ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/guard-fixture",
    "DATABASE_URL": "postgresql://guard:guard@127.0.0.1:1/guard",
    "SUMMITFLOW_JOURNAL_ALERTS": "0",
    "AGENT_HUB_EXTERNAL_ID": "task-1",
    "XDG_STATE_HOME": "/tmp/guard-corpus-state",
}
CWD = "/tmp"


def _hook_reason(command: str, extra_env: dict[str, str] | None = None) -> str:
    payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": CWD})
    result = subprocess.run(["bash", str(HOOK)], input=payload, text=True, capture_output=True, timeout=60,
                            env={**ENV, **(extra_env or {})}, check=False)
    assert result.returncode == 0, (command, result.stderr)
    output = json.loads(result.stdout)
    return "allow" if output == {} else output["hookSpecificOutput"]["permissionDecisionReason"]


def _shell(command: str) -> list[object]:
    result = subprocess.run([str(COMMAND_GUARD), "--shell-command", command, "--cwd", CWD, "--json"],
                            text=True, capture_output=True, timeout=120, env=ENV, check=False)
    return [result.returncode, result.stdout, result.stderr.strip()]


def _run(entry: dict[str, object]) -> dict[str, object]:
    command = str(entry["command"])
    return {
        "command": command,
        "hook": _hook_reason(command),
        "hook_unfiltered": _hook_reason(command, {"SF_COMMAND_GUARD_PREFILTER": "0"}),
        "fallback": _hook_reason(command, {"SF_COMMAND_GUARD_FORCE_FALLBACK": "1", "SF_COMMAND_GUARD_PREFILTER": "0"}),
        "shell": _shell(command),
    }


@pytest.fixture(scope="module")
def actual() -> list[dict[str, object]]:
    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(_run, CORPUS))


def _mismatches(actual: list[dict[str, object]], field: str, expected_field: str | None = None) -> list[str]:
    return [
        f"{want['command']!r}: expected {want[expected_field or field]!r}, got {got[field]!r}"
        for want, got in zip(CORPUS, actual, strict=True)
        if got[field] != want[expected_field or field]
    ]


def test_corpus_covers_every_policy_family() -> None:
    denied = [entry for entry in CORPUS if entry["hook"] != "allow"]
    blocked = [entry for entry in CORPUS if entry["shell"][0] == 2]
    assert len(CORPUS) > 900
    assert len(denied) > 150
    assert len(blocked) > 150
    reasons = " ".join(str(entry["hook"]) for entry in denied).lower()
    for family in ("publication", "hook", "recursive delete", "bulk delete", "backup", "snapshot", "filesystem"):
        assert family in reasons, family


def test_hook_decisions_are_unchanged(actual: list[dict[str, object]]) -> None:
    assert _mismatches(actual, "hook") == []


def test_prefilter_only_skips_calls_the_policy_allows(actual: list[dict[str, object]]) -> None:
    assert _mismatches(actual, "hook_unfiltered", "hook") == []


def test_degraded_fallback_decisions_are_unchanged(actual: list[dict[str, object]]) -> None:
    assert _mismatches(actual, "fallback") == []


def test_shell_command_decisions_are_unchanged(actual: list[dict[str, object]]) -> None:
    assert _mismatches(actual, "shell") == []


def test_hook_start_skips_modules_only_other_paths_need() -> None:
    """The hook runs on every agent shell call: its imports are part of the latency budget."""
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]); import app.services.publication_hook;"
        "print(sorted({'dataclasses', 'subprocess', 'inspect', 'typing'} & set(sys.modules)))"
    )
    result = subprocess.run(["/usr/bin/python3", "-I", "-S", "-c", probe, str(REPO / "backend")],
                            text=True, capture_output=True, check=True, timeout=10)
    assert result.stdout.strip() == "[]"


def test_shell_guard_defers_ownership_imports() -> None:
    """Ownership checks pull in the Agent Hub client and the database stack; only git rm/checkout/... need them."""
    import os
    import sys

    probe = (
        "import sys; import app.services.command_guard as g;"
        "print(sorted(m for m in ('app.services.destructive_path_guard', 'agent_hub', 'httpx', 'psycopg') if m in sys.modules));"
        "g.check_destructive_paths.__call__; g.staged_destructive_paths.__call__"
    )
    result = subprocess.run([sys.executable, "-c", probe], text=True, capture_output=True, check=True, timeout=30,
                            cwd=REPO / "backend", env={**os.environ, "PYTHONPATH": str(REPO / "backend")})
    assert result.stdout.strip() == "[]"


def test_shell_guard_without_runtime_refuses_every_command(tmp_path: Path) -> None:
    lib = tmp_path / "checkout/scripts/lib"
    lib.mkdir(parents=True)
    guard = lib / "command-guard"
    guard.write_text(COMMAND_GUARD.read_text())
    guard.chmod(0o755)
    for command in ("ls", "git push origin main"):
        result = subprocess.run([str(guard), "--shell-command", command, "--cwd", "/tmp"], text=True,
                                capture_output=True, timeout=10, env=ENV, check=False)
        assert result.returncode == 1
        assert "unavailable" in result.stderr
