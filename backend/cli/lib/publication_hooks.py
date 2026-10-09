"""CLI-only native startup status and supported, narrowly reviewed Codex hook trust."""

from __future__ import annotations

import argparse
import json
import os
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[3]
_GUARD_COMMAND = f"bash {_ROOT}/scripts/lib/publication-pretool-hook"
_STARTUP_COMMAND = f"bash {_ROOT}/scripts/lib/publication-startup-hook"


class HookReviewError(RuntimeError):
    pass


class _CodexRPC:
    def __init__(self) -> None:
        self.process = subprocess.Popen(["codex", "app-server", "--stdio"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.selector = selectors.DefaultSelector()
        assert self.process.stdout is not None
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b""
        self.sequence = 0
        try:
            self.request("initialize", {"clientInfo": {"name": "st-publication-hook-review", "version": "1.0"},
                                        "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def send(self, payload: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                payload = json.loads(line)
                if payload.get("id") == request_id:
                    if "error" in payload:
                        raise HookReviewError("Codex hook RPC refused the request.")
                    return payload["result"]
            if self.selector.select(max(0, deadline - time.monotonic())):
                assert self.process.stdout is not None
                block = os.read(self.process.stdout.fileno(), 65536)
                if not block:
                    raise HookReviewError("Codex hook RPC closed unexpectedly.")
                self.buffer += block
        raise HookReviewError("Codex hook RPC timed out.")

    def close(self) -> None:
        self.selector.close()
        self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)


def codex_hook_status(cwd: str, *, review: bool = False) -> list[dict[str, Any]]:
    """Use the same hooks/list and config/batchWrite flow as Codex /hooks.

    Review is restricted to the three installed definitions whose commands,
    matchers and event names are checked here. No manual hash calculation or
    trust bypass is used; unrelated hooks and settings remain untouched.
    """
    rpc = _CodexRPC()
    try:
        response = rpc.request("hooks/list", {"cwds": [cwd]})
        entries = response.get("data", [])
        hooks = [hook for entry in entries for hook in entry.get("hooks", [])
                 if hook.get("command") in {_GUARD_COMMAND, _STARTUP_COMMAND}]
        if len(hooks) != 3 or {hook.get("eventName") for hook in hooks} != {"preToolUse", "sessionStart", "subagentStart"} or any(entry.get("errors") for entry in entries):
            raise HookReviewError("Expected publication hooks are missing or invalid.")
        for hook in hooks:
            event = hook.get("eventName")
            expected = _GUARD_COMMAND if event == "preToolUse" else _STARTUP_COMMAND
            if event not in {"preToolUse", "sessionStart", "subagentStart"} or hook.get("command") != expected or not hook.get("enabled"):
                raise HookReviewError("Publication hook definition differs from the reviewed configuration.")
            if Path(hook.get("sourcePath", "")).resolve() != (Path.home() / ".codex/hooks.json").resolve() or hook.get("handlerType") != "command" or hook.get("async"):
                raise HookReviewError("Publication hook source or handler differs from reviewed configuration.")
            if hook.get("timeoutSec") != (5 if event == "preToolUse" else 30):
                raise HookReviewError("Publication hook timeout differs from reviewed configuration.")
            if event == "preToolUse" and hook.get("matcher") != "Bash|mcp__.*(?:github|git).*":
                raise HookReviewError("Publication tool matcher differs from reviewed configuration.")
            if event != "preToolUse" and hook.get("matcher") is not None:
                raise HookReviewError("Publication startup matcher differs from reviewed configuration.")
        if review:
            value = {hook["key"]: {"trusted_hash": hook["currentHash"]} for hook in hooks}
            rpc.request("config/batchWrite", {"edits": [{"keyPath": "hooks.state", "value": value,
                                                         "mergeStrategy": "upsert"}], "reloadUserConfig": True})
            response = rpc.request("hooks/list", {"cwds": [cwd]})
            hooks = [hook for entry in response.get("data", []) for hook in entry.get("hooks", [])
                     if hook.get("command") in {_GUARD_COMMAND, _STARTUP_COMMAND}]
        return [{"event": hook["eventName"], "key": hook["key"], "hash": hook["currentHash"],
                 "trust": hook["trustStatus"], "enabled": hook["enabled"]} for hook in hooks]
    finally:
        rpc.close()


def startup_context(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("hook_event_name", "SessionStart")
    if event not in {"SessionStart", "SubagentStart"}:
        raise ValueError("Unsupported startup event")
    cwd = str(payload.get("cwd") or os.getcwd())
    # Healthy enforcement is silent; every session and subagent pays for each line.
    lines: list[str] = []
    try:
        status = codex_hook_status(cwd)
        pending = [hook["event"] for hook in status if hook["trust"] not in {"trusted", "managed"}]
        if pending:
            lines.append("Publication hooks: review pending for " + ", ".join(pending))
    except Exception:
        lines.append("Publication hooks: Codex trust unavailable; enforcement is not verified.")
    global_hook = Path.home() / ".config/git/hooks/pre-push"
    try:
        installed = "scripts/lib/publication-pre-push" in global_hook.read_text()
    except OSError:
        installed = False
    if not installed:
        lines.append("Git outgoing verifier: adapter unavailable; installation required.")
    if not shutil.which("gitleaks"):
        lines.append("Outgoing secret scanner unavailable; publication fails closed.")
    try:
        claude_adapter = Path.home() / ".claude/hooks/PreToolUse.sh"
        claude_installed = "scripts/lib/publication-pretool-hook" in claude_adapter.read_text()
    except OSError:
        claude_installed = False
    if not claude_installed:
        lines.append("Claude publication adapter: unavailable; enforcement is not verified.")
    if not lines:
        return {}
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n".join(lines)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-codex", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--cwd", default=os.getcwd())
    args = parser.parse_args()
    if args.status or args.review_codex:
        try:
            print(json.dumps(codex_hook_status(args.cwd, review=args.review_codex), sort_keys=True))
        except Exception as exc:
            print(f"Hook review unavailable: {type(exc).__name__}", file=sys.stderr)
            return 1
    else:
        try:
            print(json.dumps(startup_context(json.load(sys.stdin))))
        except Exception:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                               "additionalContext": "Publication startup status unavailable; inspect st vcs publication."}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
