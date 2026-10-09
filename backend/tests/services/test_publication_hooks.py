from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cli.lib import publication_hooks as hooks


def _definitions():
    return [{"key": event, "eventName": event, "enabled": True, "currentHash": "sha256:" + event,
             "sourcePath": str(Path.home() / ".codex/hooks.json"), "handlerType": "command", "async": False,
             "timeoutSec": 5 if event == "preToolUse" else 30,
             "trustStatus": "untrusted", "command": hooks._GUARD_COMMAND if event == "preToolUse" else hooks._STARTUP_COMMAND,
             "matcher": "Bash|mcp__.*(?:github|git).*" if event == "preToolUse" else None}
            for event in ("preToolUse", "sessionStart", "subagentStart")]


def test_review_uses_supported_hash_write_and_preserves_other_hooks() -> None:
    with patch.object(hooks, "_CodexRPC") as rpc:
        client = rpc.return_value
        definitions = _definitions()
        trusted = [{**entry, "trustStatus": "trusted"} for entry in definitions]
        client.request.side_effect = [
            {"data": [{"hooks": [*definitions, {"key": "lease", "command": "lease-check"}]}]},
            {"status": "ok"}, {"data": [{"hooks": trusted}]},
        ]
        status = hooks.codex_hook_status("/fixture", review=True)
    assert all(entry["trust"] == "trusted" for entry in status)
    write = client.request.call_args_list[1]
    assert write.args[0] == "config/batchWrite"
    assert write.args[1]["edits"][0]["keyPath"] == "hooks.state"
    assert set(write.args[1]["edits"][0]["value"]) == {"preToolUse", "sessionStart", "subagentStart"}


def test_review_refuses_unexpected_definition() -> None:
    with patch.object(hooks, "_CodexRPC") as rpc:
        definitions = _definitions()
        definitions[0]["matcher"] = "Write"
        rpc.return_value.request.return_value = {"data": [{"hooks": definitions}]}
        with pytest.raises(hooks.HookReviewError):
            hooks.codex_hook_status("/fixture", review=True)
        assert rpc.return_value.request.call_count == 1


@pytest.mark.parametrize("event", ["SessionStart", "SubagentStart"])
def test_startup_uses_native_context_and_warns_pending(event, tmp_path: Path) -> None:
    with (
        patch.object(hooks, "codex_hook_status", return_value=[{"event": "PreToolUse", "trust": "untrusted"}]),
        patch.object(hooks.subprocess, "run", side_effect=AssertionError("Startup must not inspect publication")) as run,
        patch.object(Path, "home", return_value=tmp_path),
    ):
        result = hooks.startup_context({"hook_event_name": event, "cwd": str(tmp_path)})
    context = result["hookSpecificOutput"]
    assert context["hookEventName"] == event
    assert "review pending" in context["additionalContext"]
    assert "Nightly" not in context["additionalContext"]
    run.assert_not_called()
