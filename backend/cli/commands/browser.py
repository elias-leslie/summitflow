"""SummitFlow browser policy adapter for the supported owner executable."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import typer

from app.services.browser_routes import (
    BrowserRouteError,
    resolve_browser_location,
    resolve_browser_project_route,
)
from app.services.browser_targets import (
    BrowserEndpoint,
    BrowserTargetError,
    resolve_browser_endpoint,
)

from ..details import current_root, summary_hint
from ..lib import browser_policy, browser_support
from ..lib.usage import usage
from ..output import output_error

__all__ = ["summary_hint"]

app = typer.Typer(
    help="Remote browser automation. Uses the managed browser runner.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    add_help_option=False,
)

_ENGINE_PORTS = browser_support.ENGINE_PORTS
_DEFAULT_BROWSER_VM_ID = browser_support.DEFAULT_BROWSER_VM_ID
_AGENT_BROWSER_OPTIONS_WITH_VALUE = browser_support.AGENT_BROWSER_OPTIONS_WITH_VALUE
_HELP_ARGS = browser_policy.HELP_ARGS
_NAVIGATION_COMMANDS = browser_policy.NAVIGATION_COMMANDS
_DEFAULT_VIEWPORT_WIDTH = "1600"
_DEFAULT_VIEWPORT_HEIGHT = "900"
_ENDPOINT_FORMATS = {"http", "ws", "json"}
_ENDPOINT_USAGE = "Usage: st browser endpoint [--http|--ws|--json|--format http|ws|json]"
_URL_USAGE = "Usage: st browser url <project-or-url>"

_st_bin = browser_support.st_bin
_default_browser_vm_host = browser_support.default_browser_vm_host
_select_browser_vm_ip = browser_support.select_browser_vm_ip
_http_json = browser_support.http_json
_engine_up = browser_support.engine_up
_normalize_ws = browser_support.normalize_ws
_clean_session_component = browser_support.clean_session_component
_default_browser_session = browser_support.default_browser_session
_has_session_arg = browser_support.has_session_arg
_session_args = browser_support.session_args
_agent_command = browser_support.agent_command
_suffixed = browser_support.suffixed
_json_from_agent_eval = browser_support.json_from_agent_eval
_close_blank_browser_targets = browser_support.close_blank_browser_targets
_local_url_confirmation_token = browser_policy.local_url_confirmation_token
_local_browser_url_error = browser_policy.local_browser_url_error
_local_ai_lock_path = browser_policy.local_ai_lock_path
_local_ai_command_lock = browser_policy.local_ai_command_lock
_local_ai_window_mode = browser_policy.local_ai_window_mode
_local_ai_session = browser_policy.local_ai_session
_system_chrome_path = browser_policy.system_chrome_path


def _browser_target_env() -> dict[str, str]:
    return browser_support.browser_target_env(os.environ, default_browser_vm_host=_default_browser_vm_host)


def _resolve_endpoint(engine: str | None = None) -> BrowserEndpoint:
    return resolve_browser_endpoint(env=_browser_target_env(), engine=engine)


def _explicit_browser_port(engine: str | None = None) -> int | None:
    values = _browser_target_env()
    if values.get("ST_BROWSER_PORT", "").strip() or values.get("SUMMITFLOW_LIVE_BROWSER_PORT", "").strip():
        try:
            return resolve_browser_endpoint(env=values, engine=engine).port
        except BrowserTargetError as exc:
            output_error(str(exc))
            raise typer.Exit(1) from None
    return None


def _host_for_engine(engine: str | None = None) -> str:
    try:
        return _resolve_endpoint(engine).host
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _host() -> str:
    return _host_for_engine()


def _agent_browser_bin() -> str:
    configured = os.environ.get("AGENT_BROWSER_BIN", "").strip()
    if candidate := browser_support.agent_browser_bin(configured):
        return candidate
    output_error("agent-browser binary not found; run st setup browser")
    raise typer.Exit(127)


def _cdp_ws(port: int, *, host: str | None = None) -> str | None:
    return browser_support.cdp_ws(port, host=host or _host())


def _select_port(engine: str | None) -> int:
    host = _host_for_engine(engine)
    explicit = _explicit_browser_port(engine)
    candidates = (explicit,) if explicit else ((9223, 9222) if engine == "lightpanda" else (9222, 9223))
    for port in candidates:
        if port is not None and _engine_up(port, host=host):
            return port
    if explicit:
        output_error(f"Configured browser port is not available on {host}:{explicit}")
    else:
        output_error(f"No browser engines available on {host}")
    raise typer.Exit(1)


def _parse_browser_target_args(args: list[str]) -> tuple[str, list[str]]:
    return browser_policy.parse_target_args(args)


def _parse_engine_args(args: list[str]) -> tuple[str | None, list[str]]:
    engine, remaining, error = browser_support.parse_engine_args(
        args, initial_engine=os.environ.get("ST_BROWSER_ENGINE", "").strip() or None
    )
    if error:
        output_error(error)
        raise typer.Exit(2)
    return engine, remaining


def _resolve_guarded_browser_location(value: str) -> str:
    return browser_policy.resolve_guarded_location(value)


def _with_local_ai_session(args: list[str]) -> list[str]:
    try:
        return browser_policy.with_local_ai_session(args)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(75) from None


def _local_ai_agent_args(args: list[str]) -> list[str]:
    try:
        launch = browser_policy.local_launch(args, agent_browser_bin=_agent_browser_bin())
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    prefix = launch["prefix"]
    assert isinstance(prefix, list)
    return [*(str(item) for item in prefix), *args]


def _run_local_ai_agent(args: list[str]):
    """Lazy public-owner compatibility path used by existing core consumers."""
    scoped = _with_local_ai_session(args)
    try:
        launch = browser_policy.local_launch(scoped, agent_browser_bin=_agent_browser_bin())
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    from browser_automation.engine import run_agent_compat

    prefix = launch["prefix"]
    assert isinstance(prefix, list)
    return run_agent_compat(
        agent_browser_bin=str(launch["agent_browser_bin"]),
        prefix=[str(item) for item in prefix],
        args=scoped,
        window_mode=str(launch["window_mode"]),
        default_launch=bool(launch["default_launch"]),
        minimize=bool(launch["minimize"]),
        window_class=str(launch["window_class"]),
    )


def _run_local_ai_startup_command(args: list[str]):
    result = _run_local_ai_agent(args)
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if result.returncode != 0 and "Failed to connect: No such file or directory" in output:
        import time

        time.sleep(0.5)
        return _run_local_ai_agent(args)
    return result


def _absolute_local_output_path(path: str) -> str:
    return browser_policy.absolute_output_path(path)


def _with_resolved_local_screenshot_path(args: list[str], command: str) -> list[str]:
    if command != "screenshot":
        return args
    index = browser_policy.command_index(args)
    if index is None or index + 1 >= len(args):
        return args
    resolved = [*args]
    resolved[index + 1] = _absolute_local_output_path(resolved[index + 1])
    return resolved


def _parse_endpoint_format(args: list[str]) -> str | None:
    if not args:
        return "http"
    if args[0] in {"--ws", "ws"}:
        return "ws"
    if args[0] in {"--http", "http"}:
        return "http"
    if args[0] in {"--json", "json"}:
        return "json"
    return args[1] if args[0] == "--format" and len(args) >= 2 else None


def _browser_endpoint(args: list[str], engine: str | None) -> int:
    output_format = _parse_endpoint_format(args)
    if output_format is None:
        output_error(_ENDPOINT_USAGE)
        return 2
    if output_format not in _ENDPOINT_FORMATS:
        output_error("Browser endpoint format must be http, ws, or json")
        return 2
    port, host = _select_port(engine), _host_for_engine(engine)
    ws = _cdp_ws(port, host=host)
    if not ws:
        output_error(f"Unable to resolve browser CDP endpoint on {host}:{port}")
        return 1
    if output_format == "ws":
        print(ws)
    elif output_format == "json":
        print(json.dumps({"engine": engine or "auto", "host": host, "port": port, "http": f"http://{host}:{port}", "ws": ws}))
    else:
        print(f"http://{host}:{port}")
    return 0


def _browser_url(args: list[str]) -> int:
    if not args:
        output_error(_URL_USAGE)
        return 2
    try:
        route = resolve_browser_project_route(args[0])
    except BrowserRouteError as exc:
        output_error(str(exc))
        return 2
    print(f"{route.url} # {route.project_id} {route.source}")
    return 0


def _with_navigation(args: list[str], command: str, *, guarded: bool) -> list[str]:
    if command not in _NAVIGATION_COMMANDS:
        return args
    index = browser_policy.command_index(args)
    if index is None or index + 1 >= len(args):
        return args
    resolved = [*args]
    try:
        resolved[index + 1] = (
            _resolve_guarded_browser_location(resolved[index + 1])
            if guarded
            else resolve_browser_location(resolved[index + 1])
        )
    except BrowserRouteError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    return resolved


def _agent_browser_reaper() -> str | None:
    candidate = browser_support.agent_browser_reaper(
        os.environ.get("AGENT_BROWSER_REAPER_BIN", "").strip(), command_file=Path(__file__)
    )
    return candidate if Path(candidate).is_file() else None


def _endpoint_payload(engine: str | None, *, live: bool) -> dict[str, object]:
    try:
        endpoint = _resolve_endpoint(engine)
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    if live:
        port = _select_port(engine)
        ws = _cdp_ws(port, host=endpoint.host)
        if not ws:
            output_error(f"Unable to resolve browser CDP endpoint on {endpoint.host}:{port}")
            raise typer.Exit(1)
    else:
        port, ws = endpoint.port, f"ws://{endpoint.host}:{endpoint.port}"
    return {"host": endpoint.host, "port": port, "ws": ws, "source": endpoint.source, "debug_local": endpoint.debug_local}


def _check_payload(target: str, args: list[str]) -> tuple[list[str], dict[str, object]]:
    session = None
    if args[:1] == ["--session"]:
        if len(args) < 2:
            output_error("--session requires a name")
            raise typer.Exit(2)
        session, args = args[1], args[2:]
    if not args:
        output_error(f"Usage: st browser {'--local-ai ' if target == 'local-ai' else ''}check [--session <name>] <url> [screenshot-path]")
        raise typer.Exit(2)
    try:
        url = resolve_browser_location(args[0]) if target == "local-ai" else _resolve_guarded_browser_location(args[0])
    except BrowserRouteError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    screenshot = args[1] if len(args) > 1 else ("/tmp/st-browser-local-ai-check.png" if target == "local-ai" else "/tmp/st-browser-check.png")
    if target == "local-ai":
        screenshot = _absolute_local_output_path(screenshot)
        try:
            session = browser_policy.with_local_ai_session(["--session", session or _local_ai_session()])[1]
        except ValueError as exc:
            output_error(str(exc))
            raise typer.Exit(75) from None
    else:
        session = session or f"st-browser-check-{os.getpid()}-{time.time_ns()}"
    viewports = [
        {"label": "desktop", "width": int(os.environ.get("ST_BROWSER_CHECK_DESKTOP_WIDTH", "1600")), "height": int(os.environ.get("ST_BROWSER_CHECK_DESKTOP_HEIGHT", "900")), "path": screenshot},
        {"label": "narrow", "width": int(os.environ.get("ST_BROWSER_CHECK_NARROW_WIDTH", "1180")), "height": int(os.environ.get("ST_BROWSER_CHECK_NARROW_HEIGHT", "900")), "path": _suffixed(screenshot, "-narrow")},
        {"label": "mobile", "width": int(os.environ.get("ST_BROWSER_CHECK_MOBILE_WIDTH", "390")), "height": int(os.environ.get("ST_BROWSER_CHECK_MOBILE_HEIGHT", "844")), "path": _suffixed(screenshot, "-mobile")},
    ]
    if os.environ.get("ST_BROWSER_CHECK_RESPONSIVE") == "0":
        viewports = viewports[:1]
    return ["--session", session, "check", url, screenshot], {
        "url": url, "screenshot_path": screenshot, "session": session, "viewports": viewports,
        "settle_ms": os.environ.get("ST_BROWSER_CHECK_SETTLE_MS", "500"),
        "viewport_settle_ms": os.environ.get("ST_BROWSER_CHECK_VIEWPORT_SETTLE_MS", "350"),
    }


def _build_request(argv: list[str], context: dict[str, Any]) -> tuple[dict[str, object], bool]:
    target, args = _parse_browser_target_args(argv)
    engine, browser_args = _parse_engine_args(args)
    command = _agent_command(browser_args)
    if command == "url":
        raise typer.Exit(_browser_url(browser_args[1:]))
    if command == "endpoint":
        if target == "local-ai":
            output_error("st browser endpoint targets Proxmox/VM CDP; rerun with `st browser --proxmox endpoint`")
            raise typer.Exit(2)
        raise typer.Exit(_browser_endpoint(browser_args[1:], engine))
    if not command:
        output_error("Usage: st browser <agent-browser command> [args...]")
        raise typer.Exit(2)
    operation = command if command in {"check", "health", "update"} else "agent"
    agent_bin = "agent-browser" if target == "proxmox" and operation == "health" else _agent_browser_bin()
    check = None
    if operation == "check":
        index = browser_policy.command_index(browser_args)
        browser_args, check = _check_payload(target, browser_args[index + 1 :] if index is not None else [])
    if target == "local-ai":
        if operation == "update":
            launch = {
                "agent_browser_bin": agent_bin,
                "prefix": [],
                "window_mode": "none",
                "default_launch": False,
                "minimize": False,
                "window_class": "",
            }
        elif operation == "health":
            browser_args = ["--session", _local_ai_session(), *browser_args]
        if operation != "update":
            if operation not in {"health", "check"}:
                browser_args = _with_local_ai_session(browser_args)
            if operation == "agent":
                browser_args = _with_navigation(browser_args, command, guarded=False)
                browser_args = _with_resolved_local_screenshot_path(browser_args, command)
            try:
                launch = browser_policy.local_launch(browser_args, agent_browser_bin=agent_bin)
            except ValueError as exc:
                output_error(str(exc))
                raise typer.Exit(1) from None
        endpoint = None
    else:
        if operation == "agent":
            browser_args = _with_navigation(browser_args, command, guarded=True)
            if not _has_session_arg(browser_args) and not os.environ.get("AGENT_BROWSER_SESSION", "").strip():
                browser_args = ["--session", _default_browser_session(), *browser_args]
        endpoint = None if operation == "update" else _endpoint_payload(engine, live=operation in {"agent", "check"})
        launch = {"agent_browser_bin": agent_bin, "prefix": [], "window_mode": "remote", "default_launch": False, "minimize": False, "window_class": ""}
    default_viewport = None
    if target == "proxmox" and operation == "agent" and command == "open" and os.environ.get("ST_BROWSER_DISABLE_DEFAULT_VIEWPORT") != "1":
        default_viewport = {"width": os.environ.get("ST_BROWSER_VIEWPORT_WIDTH", _DEFAULT_VIEWPORT_WIDTH), "height": os.environ.get("ST_BROWSER_VIEWPORT_HEIGHT", _DEFAULT_VIEWPORT_HEIGHT)}
    root = Path(context.get("project_root") or current_root()).resolve()
    request: dict[str, object] = {
        "contract_version": 1, "operation": operation, "target": target, "command": command,
        "args": browser_args, "root": str(root), "endpoint": endpoint, "launch": launch,
        "check": check, "default_viewport": default_viewport,
        "reaper": "bundled" if target == "proxmox" else None,
    }
    return request, target == "local-ai" and operation in {"agent", "check"}


def run_registered(record: Any, argv: list[str], context: dict[str, Any]) -> int:
    """Apply core policy, then execute one opaque owner request within the local lock."""
    if not argv or argv[0] in _HELP_ARGS or (len(argv) > 1 and argv[1] in _HELP_ARGS):
        print(_USAGE)
        return 0
    request, needs_lock = _build_request(argv, context)
    from ..extensions import dispatch_extension

    owner_args = ["--request", json.dumps(request, separators=(",", ":"))]
    if not needs_lock:
        return dispatch_extension(record, owner_args, context=context)
    with _local_ai_command_lock() as acquired:
        if not acquired:
            output_error("LOCAL_AI_BUSY: another host-local browser operation is active; use `st browser --proxmox ...` for parallel work")
            return 75
        return dispatch_extension(record, owner_args, context=context)


_USAGE = """Remote browser automation through st

Default target:
  Plain st browser commands use local system Chrome profile AI.
  Force Proxmox/VM with --proxmox or ST_BROWSER_TARGET=proxmox when VM isolation is better.
  Override VM with ST_BROWSER_HOST, ST_BROWSER_DEFAULT_HOST, or ST_BROWSER_VM_ID.
  Do not start arbitrary Chrome, CDP proxies, or agent-browser on the project/server host.
  The approved local default is the local-AI profile flow.
  Set ST_BROWSER_DISABLE_DEFAULT_VM_HOST=1 to require explicit host config.

Usage:
  st browser health
  st browser --local-ai health
  st browser --local-ai open <project-or-url>
  st browser --proxmox check <project-or-url> [screenshot-path]
  st browser url <project>
  st browser check [--session <name>] <project-or-url> [screenshot-path]
  st browser open <project-or-url>
  st browser screenshot [path]
  st browser snapshot
  st browser eval <js>
  st browser --proxmox endpoint [--http|--ws|--json]
  st browser update
  st browser [--chrome|--lp|--engine <name>] <agent-browser command> [args...]

Examples:
  st browser --local-ai open portfolio-ai
  st browser --local-ai check portfolio-ai /tmp/portfolio-ai.png
  st browser health
  st browser url a-term
  st browser check a-term /tmp/a-term.png
  st browser --proxmox endpoint --ws
  st vm status <browser-vm-id>
  ST_BROWSER_HOST=<browser-vm-or-connector> st browser health
  ST_BROWSER_HOST=<browser-vm-or-connector> st browser check http://app.lan:3001 /tmp/page.png
  st browser --proxmox snapshot

Proxmox local page URL guard:
  With --proxmox, localhost/127.0.0.1 targets are blocked because they point at the browser VM.
  Use st browser url <project>; intentional Proxmox local targets print a confirmation token.

Debug local CDP override:
  ST_BROWSER_HOST=127.0.0.1 ST_BROWSER_ALLOW_LOCAL=1 st browser health

Local system Chrome:
  Default mode uses system Chrome, profile `AI`, headless hardware GL, and no
  software-rasterizer fallback. It creates no desktop window or focus change.
  The host-local browser is a singleton; route parallel browser work through --proxmox.
  Window control: ST_BROWSER_LOCAL_AI_VISIBLE=1 creates a normal watched window;
  ST_BROWSER_LOCAL_AI_MINIMIZED=1 creates a minimized window. Both are explicit-only.
  Override local Chrome with ST_BROWSER_LOCAL_CHROME, ST_BROWSER_LOCAL_AI_PROFILE.

Local desktop UI:
  Use st ui when the already-open desktop/PWA is the right evidence source or browser automation is not enough.
"""
_HELP = _USAGE


@app.callback(invoke_without_command=True)
@usage(
    surface="st.browser", cmd="st browser check <url> <png>",
    when="UI render verification; screenshots; DOM snapshots",
    precautions=(
        "plain st browser uses local Chrome AI profile by default",
        "use --proxmox or ST_BROWSER_TARGET=proxmox when VM isolation is better for the task",
        "use st ui when the open desktop/PWA is the right evidence source",
        "never start arbitrary chrome/CDP on project or server host; local-AI is the approved local profile flow",
        "only set ST_BROWSER_HOST / ST_BROWSER_VM_ID for explicit approved override",
    ),
    task_types=("frontend", "ui-design", "design-review", "verification"), tier="mandate",
)
def browser(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if not ctx.args or ctx.args[0] in _HELP_ARGS:
        print(_USAGE)
        raise typer.Exit(0)
    output_error("st browser owner registration is unavailable")
    raise typer.Exit(127)
