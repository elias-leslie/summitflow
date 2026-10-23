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
