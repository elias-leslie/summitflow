"""Shared helpers for the `st browser` command."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import cast

import httpx

ENGINE_PORTS = {"chrome": 9222, "lightpanda": 9223}
DEFAULT_BROWSER_VM_ID = "100"
SESSION_NAME_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9_-]+")
AGENT_BROWSER_OPTIONS_WITH_VALUE = {
    "--allowed-domains",
    "--args",
    "--cdp",
    "--config",
    "--device",
    "--download-path",
    "--engine",
    "--executable-path",
    "--extension",
    "--headers",
    "--model",
    "--profile",
    "--provider",
    "--proxy",
    "--proxy-bypass",
    "--screenshot-dir",
    "--screenshot-format",
    "--screenshot-quality",
    "--session",
    "--session-name",
    "--selected-tab",
    "--state",
    "--user-agent",
}

# Structured actions execute inside one host-selected launch/session. Command
# options remain opaque, but actions cannot replace that authority.
STRUCTURED_GLOBAL_OPTIONS = (AGENT_BROWSER_OPTIONS_WITH_VALUE - {
    "--screenshot-dir", "--screenshot-format", "--screenshot-quality",
}) | {
    "--headed", "--headless",
    "--ignore-https-errors", "--allow-file-access", "--auto-connect",
    "--local-ai", "--proxmox", "--chrome", "--lp",
    "--action-policy", "--confirm-actions", "--confirm-interactive",
    "--no-auto-dialog", "--idle-timeout", "-p",
}


def read_structured_payload(path: str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read browser JSON payload: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError("browser JSON payload must be an object")
    return payload


def split_session_options(args: list[str]) -> tuple[list[str], list[str]]:
    """Extract one explicit host session without silently ignoring bad options."""
    remaining: list[str] = []
    session: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--session" or arg.startswith("--session="):
            if session:
                raise ValueError("--session may be supplied only once")
            if arg == "--session":
                index += 1
                if index == len(args) or args[index].startswith("-"):
                    raise ValueError("--session requires a name")
                name = args[index]
            else:
                name = arg.split("=", 1)[1]
            if not name.strip():
                raise ValueError("--session requires a name")
            session = ["--session", name]
        else:
            remaining.append(arg)
        index += 1
    return session, remaining


def session_lifecycle_payload(args: list[str]) -> dict[str, object]:
    """Parse host CLI spellings; the owner validates lifecycle/domain state."""
    if not args:
        raise ValueError("Usage: st browser session <create|list [--all]|status|pause|resume|close|view|lease|maintenance> ...")
    action, *tail = args
    if action in {"create", "status", "pause", "resume", "close", "view", "lease"}:
        if len(tail) != 1 or not tail[0] or tail[0].startswith("-"):
            raise ValueError(f"Usage: st browser session {action} NAME")
        return {"action": action, "name": tail[0]}
    if action == "list" and not tail:
        return {"action": action}
    if action == "list" and tail == ["--all"]:
        return {"action": action, "all": True}
    if action != "maintenance":
        raise ValueError("Usage: st browser session <create|list [--all]|status|pause|resume|close|view|lease|maintenance> ...")
    payload: dict[str, object] = {"action": action, "dry_run": True}
    index = 0
    seen = set()
    while index < len(tail):
        option, separator, value = tail[index].partition("=")
        if option in seen:
            raise ValueError(f"Repeated session maintenance option: {option}")
        seen.add(option)
        if option == "--apply" and not separator:
            payload["dry_run"] = False
        elif option == "--idle-ms":
            if not separator:
                index += 1
                if index == len(tail):
                    raise ValueError("--idle-ms requires a positive integer")
                value = tail[index]
            if not value.isascii() or not value.isdecimal() or int(value) < 1:
                raise ValueError("--idle-ms requires a positive integer")
            payload["idle_ms"] = int(value)
        else:
            raise ValueError(f"Unknown session maintenance option: {tail[index]}")
        index += 1
    return payload


def selected_tab_options(args: list[str]) -> tuple[str | None, list[str]]:
    """Extract one explicit target capability before the command; never infer it."""
    remaining: list[str] = []
    selected: str | None = None
    command_seen = False
    index = 0
    while index < len(args):
        arg = args[index]
        option = arg.split("=", 1)[0]
        if option == "--selected-tab":
            if selected is not None or command_seen:
                raise ValueError("--selected-tab must appear once before the browser command")
            if "=" in arg:
                value = arg.split("=", 1)[1]
            else:
                index += 1
                value = args[index] if index < len(args) else ""
            if re.fullmatch(r"[0-9a-f]{32}", value) is None:
                raise ValueError("--selected-tab requires an opaque 32-character lowercase hexadecimal handle")
            selected = value
        else:
            remaining.append(arg)
            if not command_seen and option in AGENT_BROWSER_OPTIONS_WITH_VALUE and "=" not in arg:
                index += 1
                if index < len(args):
                    remaining.append(args[index])
            elif not arg.startswith("-"):
                command_seen = True
        index += 1
    return selected, remaining


def selected_tabs_payload(args: list[str]) -> dict[str, object]:
    if args in (["list"], ["capabilities"]):
        return {"action": args[0]}
    if len(args) == 2 and args[0] == "revoke" and re.fullmatch(r"[0-9a-f]{32}", args[1]):
        return {"action": "revoke", "handle": args[1]}
    raise ValueError("Usage: st browser selected-tabs list|capabilities|revoke HANDLE")


def workflow_payload(args: list[str]) -> dict[str, object]:
    """Build the owner workflow wire from files and explicit lifecycle options."""
    if not args or args[0] not in {"run", "resume", "cancel", "status", "record-start", "record-stop"}:
        raise ValueError("Usage: st browser --session NAME workflow <run|resume|cancel|status|record-start|record-stop> ...")
    action, *tail = args
    payload: dict[str, object] = {"action": action, "definition": None, "parameters": {}, "run_id": "", "resolution": None}
    if action != "run":
        if not tail or not tail[0] or tail[0].startswith("-"):
            raise ValueError(f"workflow {action} requires a run ID")
        payload["run_id"], tail = tail[0], tail[1:]
    allowed = {"--file", "--parameters", "--run-id"} if action == "run" else {"--step", "--resolution"} if action == "resume" else {"--file", "--parameters"} if action == "record-stop" else set()
    options: dict[str, str] = {}
    index = 0
    while index < len(tail):
        option, separator, value = tail[index].partition("=")
        if option not in allowed or option in options:
            raise ValueError(f"Unknown or repeated workflow option: {option}")
        if not separator:
            index += 1
            if index == len(tail) or tail[index].startswith("-"):
                raise ValueError(f"{option} requires a value")
            value = tail[index]
        if not value:
            raise ValueError(f"{option} requires a value")
        options[option] = value
        index += 1
    if action == "run":
        if not {"--file", "--run-id"} <= options.keys():
            raise ValueError("Usage: st browser --session NAME workflow run --file DEFINITION --run-id ID [--parameters JSON-file-or-object]")
        payload["definition"] = read_structured_payload(options["--file"])
        payload["run_id"] = options["--run-id"]
    elif action == "resume" and options:
        if set(options) != {"--step", "--resolution"} or options["--resolution"] not in {"completed", "retry"}:
            raise ValueError("workflow resume resolution requires --step ID --resolution completed|retry")
        payload["resolution"] = {"step": options["--step"], "outcome": options["--resolution"]}
    if "--parameters" in options:
        value = options["--parameters"]
        if value.lstrip().startswith(("{", "[")):
            try:
                parameters = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError("workflow parameters must be a valid JSON object") from None
            if not isinstance(parameters, dict):
                raise ValueError("workflow parameters must be a JSON object")
            payload["parameters"] = parameters
        else:
            payload["parameters"] = read_structured_payload(value)
    if action == "record-stop":
        payload["output"] = str(Path(options["--file"]).expanduser().resolve()) if "--file" in options else None
    return payload


def validate_structured_action(action: object) -> list[str]:
    if not isinstance(action, list) or not action or any(not isinstance(arg, str) for arg in action):
        raise ValueError("run actions must be nonempty arrays of strings")
    args = cast(list[str], action)
    if not args[0] or args[0].startswith("-"):
        raise ValueError("structured actions must start with a core command")
    if args[0] in {"session", "sessions", "connect", "attach", "launch"}:
        raise ValueError("structured actions cannot switch sessions or launch browsers")
    if any(arg.split("=", 1)[0] in STRUCTURED_GLOBAL_OPTIONS for arg in args[1:]):
        raise ValueError("structured actions cannot embed launch/global options or switch sessions")
    if args[0] in {"close", "quit", "exit"} and any(arg == "--all" or arg.startswith("--all=") for arg in args[1:]):
        raise ValueError("structured actions cannot close all sessions")
    return list(args)


def st_bin() -> str:
    return shutil.which("st") or sys.argv[0]


def browser_target_env(
    environ: Mapping[str, str],
    *,
    default_browser_vm_host: Callable[[dict[str, str]], str],
) -> dict[str, str]:
    values = dict(environ)
    if values.get("ST_BROWSER_HOST", "").strip() or values.get("ST_BROWSER_DEFAULT_HOST", "").strip():
        return values
    if values.get("ST_BROWSER_DISABLE_DEFAULT_VM_HOST", "").strip() == "1":
        return values
    host = default_browser_vm_host(values)
    if host:
        values["ST_BROWSER_DEFAULT_HOST"] = host
    return values


def default_browser_vm_host(values: dict[str, str]) -> str:
    vmid = values.get("ST_BROWSER_VM_ID", "").strip() or DEFAULT_BROWSER_VM_ID
    try:
        result = subprocess.run(
            [st_bin(), "vm", "ip", vmid],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return select_browser_vm_ip(result.stdout, values)


def select_browser_vm_ip(output: str, values: dict[str, str]) -> str:
    addresses = [
        line.strip() for line in output.splitlines() if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", line.strip())
    ]
    if not addresses:
        return ""
    prefix = values.get("ST_BROWSER_VM_IP_PREFIX", "").strip()
    if prefix:
        for address in addresses:
            if address.startswith(prefix):
                return address
    for address in addresses:
        if ip_address(address).is_private:
            return address
    return addresses[0]


def http_json(url: str) -> dict[str, object] | list[object] | None:
    try:
        response = httpx.get(url, timeout=2.0)
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        return None
    try:
        parsed = response.json()
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict | list) else None


def browser_page_target_ids(host: str, port: int) -> set[str] | None:
    return importlib.import_module("browser_automation.support").browser_page_target_ids(host, port)


def close_browser_targets(host: str, port: int, target_ids: set[str]) -> int:
    return importlib.import_module("browser_automation.support").close_browser_targets(host, port, target_ids)


def close_blank_browser_targets(host: str, port: int) -> int:
    return importlib.import_module("browser_automation.support").close_blank_browser_targets(host, port)


def engine_up(port: int, *, host: str) -> bool:
    return http_json(f"http://{host}:{port}/json/version") is not None


def normalize_ws(ws_url: str, port: int, *, host: str) -> str:
    return (
        ws_url.replace(f"0.0.0.0:{port}", f"{host}:{port}")
        .replace(f"127.0.0.1:{port}", f"{host}:{port}")
        .replace(f"localhost:{port}", f"{host}:{port}")
    )


def cdp_ws(port: int, *, host: str) -> str | None:
    payload = http_json(f"http://{host}:{port}/json/version")
    if not isinstance(payload, dict):
        return None
    ws_url = payload.get("webSocketDebuggerUrl")
    if not isinstance(ws_url, str) or not ws_url:
        return None
    return normalize_ws(ws_url, port, host=host)


def agent_browser_bin(configured: str, *, home: Path | None = None) -> str | None:
    home_dir = home or Path.home()
    candidates = [
        configured,
        shutil.which("agent-browser") or "",
        str(home_dir / ".local" / "bin" / "agent-browser"),
        str(home_dir / ".local" / "share" / "agent-browser-managed" / "node_modules" / ".bin" / "agent-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def agent_browser_reaper(configured: str, *, command_file: Path) -> str:
    candidate = Path(configured) if configured else command_file.resolve().parents[3] / "scripts" / "agent-browser-idle-reaper.js"
    return str(candidate)


def repo_root_for_session() -> Path:
    detected = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if detected.returncode == 0 and detected.stdout.strip():
        return Path(detected.stdout.strip())
    return Path.cwd()


def repo_branch_for_session() -> str:
    detected = subprocess.run(
        ["git", "branch", "--show-current"],
        text=True,
        capture_output=True,
        check=False,
    )
    return detected.stdout.strip() if detected.returncode == 0 else ""


def clean_session_component(value: str) -> str:
    cleaned = SESSION_NAME_SAFE_CHARS.sub("-", value.strip()).strip("-_")
    return cleaned or "session"


def default_browser_session() -> str:
    configured = os.environ.get("ST_BROWSER_SESSION", "").strip()
    if configured:
        return configured
    root = repo_root_for_session()
    branch = repo_branch_for_session()
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    label = clean_session_component("-".join(part for part in (root.name, branch) if part))
    return f"st-{label[:42]}-{digest}"


def has_session_arg(args: list[str]) -> bool:
    return any(arg == "--session" or arg.startswith("--session=") for arg in args)


def session_args(args: list[str]) -> list[str]:
    for index, arg in enumerate(args):
        if arg == "--session" and index + 1 < len(args):
            return ["--session", args[index + 1]]
        if arg.startswith("--session="):
            return ["--session", arg.split("=", 1)[1]]
    return []


def agent_command(args: list[str]) -> str:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return arg
        if arg in AGENT_BROWSER_OPTIONS_WITH_VALUE:
            index += 2
        else:
            index += 1
    return ""


def parse_engine_args(args: list[str], *, initial_engine: str | None) -> tuple[str | None, list[str], str | None]:
    engine = initial_engine
    remaining: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--chrome":
            engine = "chrome"
            index += 1
        elif arg == "--lp":
            engine = "lightpanda"
            index += 1
        elif arg == "--engine":
            if index + 1 >= len(args):
                return engine, remaining, "--engine requires a value"
            engine = args[index + 1]
            index += 2
        else:
            remaining.extend(args[index:])
            break
    return engine, remaining, None


def suffixed(path: str, suffix: str) -> str:
    target = Path(path)
    return str(target.with_name(f"{target.stem}{suffix}{target.suffix}"))


def json_from_agent_eval(raw: str) -> dict[str, object] | list[object]:
    return importlib.import_module("browser_automation.support").json_from_agent_eval(raw)


def parse_agent_console(raw: str) -> tuple[list[str], list[str]]:
    return importlib.import_module("browser_automation.support").parse_agent_console(raw)
