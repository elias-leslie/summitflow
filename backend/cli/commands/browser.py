"""Canonical browser automation command surface."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import typer

from app.services.browser_targets import BrowserTargetError, resolve_browser_endpoint

from ..output import output_error

app = typer.Typer(
    help="Remote browser automation. Uses the managed browser runner.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    add_help_option=False,
)

_ENGINE_PORTS = {"chrome": 9222, "lightpanda": 9223}
_SESSION_NAME_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9_-]+")
_AGENT_BROWSER_OPTIONS_WITH_VALUE = {
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


def _host() -> str:
    try:
        return resolve_browser_endpoint().host
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _host_for_engine(engine: str | None = None) -> str:
    try:
        return resolve_browser_endpoint(engine=engine).host
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _agent_browser_bin() -> str:
    configured = os.environ.get("AGENT_BROWSER_BIN", "").strip()
    candidates = [
        configured,
        shutil.which("agent-browser") or "",
        str(Path.home() / ".local" / "bin" / "agent-browser"),
        str(Path.home() / ".local" / "share" / "agent-browser-managed" / "node_modules" / ".bin" / "agent-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    output_error("agent-browser binary not found; run st setup browser")
    raise typer.Exit(127) from None


def _http_json(url: str) -> dict[str, object] | list[object] | None:
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


def _engine_up(port: int, *, host: str) -> bool:
    return _http_json(f"http://{host}:{port}/json/version") is not None


def _normalize_ws(ws_url: str, port: int, *, host: str) -> str:
    return (
        ws_url.replace(f"0.0.0.0:{port}", f"{host}:{port}")
        .replace(f"127.0.0.1:{port}", f"{host}:{port}")
        .replace(f"localhost:{port}", f"{host}:{port}")
    )


def _cdp_ws(port: int, *, host: str | None = None) -> str | None:
    resolved_host = host or _host()
    payload = _http_json(f"http://{resolved_host}:{port}/json/version")
    if not isinstance(payload, dict):
        return None
    ws_url = payload.get("webSocketDebuggerUrl")
    if not isinstance(ws_url, str) or not ws_url:
        return None
    return _normalize_ws(ws_url, port, host=resolved_host)


def _select_port(engine: str | None) -> int:
    host = _host_for_engine(engine)
    if engine == "lightpanda":
        return 9223 if _engine_up(9223, host=host) else 9222
    if engine == "chrome":
        return 9222 if _engine_up(9222, host=host) else 9223
    if _engine_up(9222, host=host):
        return 9222
    if _engine_up(9223, host=host):
        return 9223
    output_error(f"No browser engines available on {host}")
    raise typer.Exit(1) from None


def _run_agent(args: list[str], *, cdp: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    command = [_agent_browser_bin()]
    if cdp:
        command.extend(["--cdp", cdp])
    command.extend(args)
    return subprocess.run(command, text=True, capture_output=capture, check=False)


def _agent_browser_reaper() -> str:
    configured = os.environ.get("AGENT_BROWSER_REAPER_BIN", "").strip()
    candidate = Path(configured) if configured else Path(__file__).resolve().parents[3] / "scripts" / "agent-browser-idle-reaper.js"
    return str(candidate)


def _run_browser_reaper() -> None:
    reaper = _agent_browser_reaper()
    if Path(reaper).exists():
        subprocess.run(["node", reaper], text=True, capture_output=True, check=False)


def _repo_root_for_session() -> Path:
    detected = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if detected.returncode == 0 and detected.stdout.strip():
        return Path(detected.stdout.strip())
    return Path.cwd()


def _repo_branch_for_session() -> str:
    detected = subprocess.run(
        ["git", "branch", "--show-current"],
        text=True,
        capture_output=True,
        check=False,
    )
    return detected.stdout.strip() if detected.returncode == 0 else ""


def _clean_session_component(value: str) -> str:
    cleaned = _SESSION_NAME_SAFE_CHARS.sub("-", value.strip()).strip("-_")
    return cleaned or "session"


def _default_browser_session() -> str:
    configured = os.environ.get("ST_BROWSER_SESSION", "").strip()
    if configured:
        return configured
    root = _repo_root_for_session()
    branch = _repo_branch_for_session()
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    label = _clean_session_component("-".join(part for part in (root.name, branch) if part))
    return f"st-{label[:42]}-{digest}"


def _has_session_arg(args: list[str]) -> bool:
    return any(arg == "--session" or arg.startswith("--session=") for arg in args)


def _with_default_session(args: list[str]) -> list[str]:
    if _has_session_arg(args) or os.environ.get("AGENT_BROWSER_SESSION", "").strip():
        return args
    return ["--session", _default_browser_session(), *args]


def _session_args(args: list[str]) -> list[str]:
    for index, arg in enumerate(args):
        if arg == "--session" and index + 1 < len(args):
            return ["--session", args[index + 1]]
        if arg.startswith("--session="):
            return ["--session", arg.split("=", 1)[1]]
    return []


def _agent_command(args: list[str]) -> str:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return arg
        if arg in _AGENT_BROWSER_OPTIONS_WITH_VALUE:
            index += 2
        else:
            index += 1
    return ""


def _parse_engine_args(args: list[str]) -> tuple[str | None, list[str]]:
    engine = os.environ.get("SF_BROWSER_ENGINE", "").strip() or None
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
                output_error("--engine requires a value")
                raise typer.Exit(2) from None
            engine = args[index + 1]
            index += 2
        else:
            remaining.extend(args[index:])
            break
    return engine, remaining


def _print_health() -> None:
    try:
        endpoint = resolve_browser_endpoint()
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    host = endpoint.host
    print(f"Target: {host} ({endpoint.source}{'; debug-local' if endpoint.debug_local else ''})")
    print(f"{'ENGINE':<12} {'PORT':<6} {'STATUS':<6} DETAILS")
    for engine, port in _ENGINE_PORTS.items():
        payload = _http_json(f"http://{host}:{port}/json/version")
        if isinstance(payload, dict):
            detail = str(payload.get("Browser") or payload.get("webSocketDebuggerUrl") or "-")
            print(f"{engine:<12} {port:<6} {'UP':<6} {detail}")
        else:
            print(f"{engine:<12} {port:<6} {'DOWN':<6} -")


def _suffixed(path: str, suffix: str) -> str:
    target = Path(path)
    return str(target.with_name(f"{target.stem}{suffix}{target.suffix}"))


def _json_from_agent_eval(raw: str) -> dict[str, object] | list[object]:
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


def _browser_check(args: list[str]) -> int:
    session = None
    if args[:1] == ["--session"]:
        if len(args) < 2:
            output_error("--session requires a name")
            return 2
        session = args[1]
        args = args[2:]
    if not args:
        output_error("Usage: st browser check [--session <name>] <url> [screenshot-path]")
        return 2
    url = args[0]
    screenshot_path = args[1] if len(args) > 1 else "/tmp/st-browser-check.png"
    session_args = ["--session", session or f"st-browser-check-{os.getpid()}-{time.time_ns()}"]
    port = _select_port("chrome")
    host = _host_for_engine("chrome")
    ws = _cdp_ws(port, host=host)
    if not ws:
        output_error(f"Unable to resolve Chrome CDP endpoint on {host}:{port}")
        return 1

    try:
        viewports = [
            ("desktop", int(os.environ.get("SF_BROWSER_CHECK_DESKTOP_WIDTH", "1600")), int(os.environ.get("SF_BROWSER_CHECK_DESKTOP_HEIGHT", "900")), screenshot_path),
            ("narrow", int(os.environ.get("SF_BROWSER_CHECK_NARROW_WIDTH", "1180")), int(os.environ.get("SF_BROWSER_CHECK_NARROW_HEIGHT", "900")), _suffixed(screenshot_path, "-narrow")),
            ("mobile", int(os.environ.get("SF_BROWSER_CHECK_MOBILE_WIDTH", "390")), int(os.environ.get("SF_BROWSER_CHECK_MOBILE_HEIGHT", "844")), _suffixed(screenshot_path, "-mobile")),
        ]
        if os.environ.get("SF_BROWSER_CHECK_RESPONSIVE") == "0":
            viewports = viewports[:1]

        _run_agent([*session_args, "set", "viewport", str(viewports[0][1]), str(viewports[0][2])], cdp=ws)
        open_result = _run_agent([*session_args, "open", url], cdp=ws)
        if open_result.returncode != 0:
            return open_result.returncode
        _run_agent([*session_args, "wait", os.environ.get("SF_BROWSER_CHECK_WAIT", "5000")], cdp=ws)
        _run_agent(
            [
                *session_args,
                "eval",
                "window.__sfErrors=[];window.__sfWarnings=[];"
                "const oe=console.error;console.error=(...a)=>{window.__sfErrors.push(a.map(String).join(' '));oe.apply(console,a)};"
                "const ow=console.warn;console.warn=(...a)=>{window.__sfWarnings.push(a.map(String).join(' '));ow.apply(console,a)};'capturing'",
            ],
            cdp=ws,
        )
        _run_agent([*session_args, "wait", "2000"], cdp=ws)

        for _, width, height, path in viewports:
            _run_agent([*session_args, "set", "viewport", str(width), str(height)], cdp=ws)
            _run_agent([*session_args, "wait", os.environ.get("SF_BROWSER_CHECK_VIEWPORT_SETTLE_MS", "350")], cdp=ws)
            screenshot = _run_agent([*session_args, "screenshot", path], cdp=ws)
            if screenshot.returncode != 0:
                return screenshot.returncode

        error_result = _run_agent(
            [
                *session_args,
                "eval",
                "JSON.stringify({errors:window.__sfErrors||[],warnings:window.__sfWarnings||[],url:location.href,title:document.title})",
            ],
            cdp=ws,
            capture=True,
        )
        network_result = _run_agent(
            [
                *session_args,
                "eval",
                "JSON.stringify(performance.getEntriesByType('resource').filter(e=>e.responseStatus>=400).map(e=>e.responseStatus+' '+e.name.split('/').pop()))",
            ],
            cdp=ws,
            capture=True,
        )
    finally:
        _run_agent([*session_args, "close"], cdp=ws)
        _run_browser_reaper()
    errors = _json_from_agent_eval(error_result.stdout)
    network = _json_from_agent_eval(network_result.stdout)
    raw_errors = errors.get("errors", []) if isinstance(errors, dict) else []
    raw_warnings = errors.get("warnings", []) if isinstance(errors, dict) else []
    error_items: list[object] = [item for item in raw_errors] if isinstance(raw_errors, list) else []
    warning_items: list[object] = [item for item in raw_warnings] if isinstance(raw_warnings, list) else []
    network_items: list[object] = list(network) if isinstance(network, list) else []

    print(f"Screenshot: {screenshot_path}")
    print("Responsive set: " + ", ".join(f"{label} {width}x{height}" for label, width, height, _ in viewports))
    if len(viewports) > 1:
        print("Additional screenshots:")
        for label, _, _, path in viewports[1:]:
            print(f"  {label}: {path}")
    if isinstance(errors, dict):
        print(f"Page: {errors.get('url', 'unknown')}")
        print(f"Title: {errors.get('title', 'unknown')}")
    if error_items:
        print(f"\nConsole errors ({len(error_items)}):")
        print("\n".join(str(item) for item in error_items[:20]))
    if warning_items:
        print(f"\nConsole warnings ({len(warning_items)}):")
        print("\n".join(str(item) for item in warning_items[:10]))
    if network_items:
        print(f"\nFailed network requests ({len(network_items)}):")
        print("\n".join(str(item) for item in network_items[:20]))
    if not error_items and not warning_items and not network_items:
        print("No console errors, warnings, or failed network requests.")
    return 0


def _browser_update() -> int:
    current = _run_agent(["--version"], capture=True).stdout.strip() or "unknown"
    latest = subprocess.run(["npm", "view", "agent-browser", "version"], text=True, capture_output=True, check=False)
    print(f"agent-browser: installed={current} latest={latest.stdout.strip() or '?'}")
    print("Runtime:")
    try:
        endpoint = resolve_browser_endpoint()
        print(f"  host: {endpoint.host}")
        print(f"  source: {endpoint.source}")
        print(f"  debug_local: {endpoint.debug_local}")
    except BrowserTargetError as exc:
        print(f"  host: unavailable ({exc})")
    print(f"  agent-browser-bin: {_agent_browser_bin()}")
    return 0


def _usage() -> str:
    return """Remote browser automation through st

Usage:
  st browser health
  st browser check [--session <name>] <url> [screenshot-path]
  st browser open <url>
  st browser screenshot [path]
  st browser snapshot
  st browser eval <js>
  st browser update
  st browser [--chrome|--lp|--engine <name>] <agent-browser command> [args...]
"""


@app.callback(invoke_without_command=True)
def browser(ctx: typer.Context) -> None:
    """Run browser health, checks, screenshots, snapshots, or DOM commands.

    Examples:
      st browser health
      st browser check http://localhost:3001 /tmp/summitflow.png
    """
    if ctx.invoked_subcommand is not None:
        return
    args = list(ctx.args)
    if not args or args[0] in {"-h", "--help", "help"}:
        typer.echo(_usage())
        raise typer.Exit(0)
    engine, browser_args = _parse_engine_args(args)
    command = _agent_command(browser_args)
    if command == "health":
        _print_health()
        raise typer.Exit(0)
    if command == "check":
        raise typer.Exit(_browser_check(browser_args[1:]))
    if command == "update":
        raise typer.Exit(_browser_update())

    port = _select_port(engine)
    host = _host_for_engine(engine)
    ws = _cdp_ws(port, host=host)
    if not ws:
        output_error(f"Unable to resolve browser CDP endpoint on {host}:{port}")
        raise typer.Exit(1) from None
    scoped_browser_args = _with_default_session(browser_args)
    if command == "open" and os.environ.get("SF_BROWSER_DISABLE_DEFAULT_VIEWPORT") != "1":
        _run_agent(
            [
                *_session_args(scoped_browser_args),
                "set",
                "viewport",
                os.environ.get("SF_BROWSER_VIEWPORT_WIDTH", "1600"),
                os.environ.get("SF_BROWSER_VIEWPORT_HEIGHT", "900"),
            ],
            cdp=ws,
        )
    result = _run_agent(scoped_browser_args, cdp=ws)
    _run_browser_reaper()
    raise typer.Exit(result.returncode)
