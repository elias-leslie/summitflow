"""Exercise the real Pi adapter and inbox hook with a private coordination ledger."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from cli.lib import coord

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("configured,user_runtime_exists", [(True, True), (False, True), (False, False)])
def test_pi_seen_state_uses_the_user_runtime_when_xdg_is_absent(monkeypatch, tmp_path, configured, user_runtime_exists):
    from cli.lib import coord_wake

    user_runtime, fallback, explicit = (tmp_path / name for name in ("user-runtime", "fallback", "explicit"))
    if user_runtime_exists:
        user_runtime.mkdir()
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    if configured:
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(explicit))
    roots = {f"/run/user/{os.getuid()}": user_runtime, "/tmp": fallback}
    monkeypatch.setattr(coord_wake, "Path", lambda value: roots.get(str(value), Path(value)))
    expected = (explicit if configured else user_runtime if user_runtime_exists else fallback) / "st-coord-inbox"
    monkeypatch.setattr(coord_wake, "STATE", coord_wake._state_dir())
    assert expected == coord_wake.STATE
    expected.mkdir(parents=True, exist_ok=True)
    coord_wake.seen_path("pi:fixture").write_text(json.dumps({"fixture:req": 1}))
    assert coord.surfaced({"id": "fixture", "to": "pi:fixture"})


@pytest.mark.parametrize("tool", ["read", "edit", "write", "bash"])
def test_busy_pi_receives_a_request_once_in_tool_results(monkeypatch, tmp_path, tool):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the Pi extension fixture")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fixture-sender")
    row = coord.send("pi:560933", "Read the fixture brief", source_key="fixture:1")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "coord-inbox.sh").symlink_to(ROOT / "scripts/lib/coord-inbox")
    (hooks / "lease-check.sh").write_text(
        "#!/bin/bash\n"
        "case ${1-} in\n"
        "  '') echo '{\"hookSpecificOutput\":{\"additionalContext\":\"edit warning\"}}';;\n"
        "  bash-post) echo 'bash warning' >&2; exit 2;;\n"
        "esac\n"
    )
    script = tmp_path / "fixture.mjs"
    script.write_text("""
import {unlinkSync} from 'node:fs';
import adapter from '""" + (ROOT / "scripts/lib/pi-coord-extension.ts").as_uri() + """';
const handlers = {};
adapter({on: (name, handler) => handlers[name] = handler,
         sendUserMessage: () => { throw new Error('busy delivery must use tool context'); }});
const ctx = {isIdle: () => false, sessionManager: {
  getSessionId: () => '56093300-0000-4000-8000-000000000000', getCwd: () => process.cwd()}};
await handlers.session_start({reason: 'startup'}, ctx);
const event = {toolName: process.env.FIXTURE_TOOL, toolCallId: 'call-1', input: {path: 'fixture.txt'},
               isError: true, content: [{type: 'text', text: 'original tool result'}]};
await handlers.tool_call(event, ctx);
const first = await handlers.tool_result(event, ctx);
const second = await handlers.tool_result({...event, toolCallId: 'call-2'}, ctx);
unlinkSync(`${process.env.HOME}/.claude/hooks/coord-inbox.sh`);
const missing = await handlers.tool_result({...event, toolName: 'read', toolCallId: 'call-3'}, ctx);
handlers.session_shutdown();
console.log(JSON.stringify({first, second, missing}));
""")
    env = {**os.environ, "HOME": str(tmp_path), "XDG_RUNTIME_DIR": str(tmp_path / "run"),
           "FIXTURE_TOOL": tool, "ST_COORD_INBOX": "1", "ST_COORD_HARNESS": "pi"}
    result = subprocess.run([node, str(script)], env=env, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    outputs = json.loads(result.stdout)
    first = outputs["first"]["content"]
    assert first[0] == {"type": "text", "text": "original tool result"}
    assert sum(f"REQUEST {row['id']}" in item.get("text", "") for item in first) == 1
    if tool in ("edit", "write", "bash"):
        assert any("warning" in item.get("text", "") for item in first)
    assert f"REQUEST {row['id']}" not in json.dumps(outputs.get("second"))
    assert "missing" not in outputs  # a failed hook leaves the original result alone
    assert coord._load_ledger()[0]["state"] == "open"  # delivery does not ack or confirm


def test_pi_checks_inbox_when_the_run_has_settled(monkeypatch, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the Pi extension fixture")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "fixture-sender")
    row = coord.send("pi:560933", "Read the settled fixture brief", source_key="fixture:settled")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "coord-inbox.sh").symlink_to(ROOT / "scripts/lib/coord-inbox")
    (hooks / "lease-check.sh").write_text("#!/bin/bash\nexit 0\n")
    script = tmp_path / "settled.mjs"
    script.write_text("""
import adapter from '""" + (ROOT / "scripts/lib/pi-coord-extension.ts").as_uri() + """';
const handlers = {}, messages = [];
adapter({on: (name, handler) => handlers[name] = handler,
         sendUserMessage: (message, options) => messages.push({message, options})});
let idle = false;
const ctx = {isIdle: () => idle, sessionManager: {
  getSessionId: () => '56093300-0000-4000-8000-000000000000', getCwd: () => process.cwd()}};
await handlers.session_start({reason: 'startup'}, ctx);
await handlers.agent_end({}, ctx);  // Pi 1.4 still reports busy at agent_end.
const beforeSettled = messages.length;
idle = true;
await handlers.agent_settled({aborted: false}, ctx);
await handlers.agent_settled({aborted: false}, ctx);
handlers.session_shutdown();
console.log(JSON.stringify({beforeSettled, messages}));
""")
    env = {**os.environ, "HOME": str(tmp_path), "XDG_RUNTIME_DIR": str(tmp_path / "run"),
           "ST_COORD_INBOX": "1", "ST_COORD_HARNESS": "pi"}
    result = subprocess.run([node, str(script)], env=env, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 0, result.stderr
    outputs = json.loads(result.stdout)
    assert outputs["beforeSettled"] == 0
    assert len(outputs["messages"]) == 1
    assert f"REQUEST {row['id']}" in outputs["messages"][0]["message"]
    assert outputs["messages"][0]["options"] == {"deliverAs": "followUp"}
    assert coord._load_ledger()[0]["state"] == "open"
