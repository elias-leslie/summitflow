"""Shared helpers for the `st browser` command."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import Any, cast

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
    "--state",
    "--user-agent",
}


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
    targets = http_json(f"http://{host}:{port}/json/list")
    if not isinstance(targets, list):
        return None

    ids: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_data = cast(dict[str, Any], target)
        target_id = target_data.get("id")
        if target_data.get("type") == "page" and isinstance(target_id, str) and target_id:
            ids.add(target_id)
    return ids


def close_browser_targets(host: str, port: int, target_ids: set[str]) -> int:
    closed = 0
    for target_id in target_ids:
        try:
            response = httpx.get(f"http://{host}:{port}/json/close/{target_id}", timeout=2.0)
        except httpx.HTTPError:
            continue
        if response.status_code < 400:
            closed += 1
    return closed


def close_blank_browser_targets(host: str, port: int) -> int:
    targets = http_json(f"http://{host}:{port}/json/list")
    if not isinstance(targets, list):
        return 0

    closed = 0
    for target in targets:
        if not isinstance(target, dict):
            continue
        target_data = cast(dict[str, Any], target)
        if target_data.get("type") != "page":
            continue
        target_id = target_data.get("id")
        title = str(target_data.get("title") or "")
        url = str(target_data.get("url") or "")
        if not isinstance(target_id, str) or not target_id:
            continue
        if url != "about:blank":
            continue
        if title not in {"", "about:blank"} and not title.startswith("Starting agent "):
            continue
        closed += close_browser_targets(host, port, {target_id})
    return closed


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
    text = raw.strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, str):
            return json.loads(parsed)
        if isinstance(parsed, dict | list):
            return parsed
    except json.JSONDecodeError:
        pass
    return {}


def parse_agent_console(raw: str) -> tuple[list[str], list[str]]:
    """Split agent-browser console history into complete error and warning entries."""
    errors: list[str] = []
    warnings: list[str] = []
    active: list[str] | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("[error]", "[pageerror]")):
            errors.append(stripped)
            active = errors
        elif lowered.startswith(("[warning]", "[warn]")):
            warnings.append(stripped)
            active = warnings
        elif stripped.startswith("["):
            active = None
        elif active is not None and stripped and not stripped.startswith("⚠"):
            active[-1] = f"{active[-1]}\n{stripped}"
    return errors, warnings
