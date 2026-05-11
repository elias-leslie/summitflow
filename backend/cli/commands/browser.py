"""Canonical browser automation command surface."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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

from ..details import (
    current_root,
    display_path,
    emit_result_or_details,
    summary_hint,
    write_details,
)
from ..lib import browser_check, browser_support
from ..lib.usage import usage
from ..output import output_error

app = typer.Typer(
    help="Remote browser automation. Uses the managed browser runner.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True, "help_option_names": []},
    add_help_option=False,
)

_ENGINE_PORTS = browser_support.ENGINE_PORTS
_DEFAULT_BROWSER_VM_ID = browser_support.DEFAULT_BROWSER_VM_ID
_AGENT_BROWSER_OPTIONS_WITH_VALUE = browser_support.AGENT_BROWSER_OPTIONS_WITH_VALUE
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


def _host() -> str:
    try:
        return _resolve_endpoint().host
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _host_for_engine(engine: str | None = None) -> str:
    try:
        return _resolve_endpoint(engine=engine).host
    except BrowserTargetError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _agent_browser_bin() -> str:
    configured = os.environ.get("AGENT_BROWSER_BIN", "").strip()
    if candidate := browser_support.agent_browser_bin(configured):
        return candidate
    output_error("agent-browser binary not found; run st setup browser")
    raise typer.Exit(127) from None


def _cdp_ws(port: int, *, host: str | None = None) -> str | None:
    return browser_support.cdp_ws(port, host=host or _host())


def _select_port(engine: str | None) -> int:
    host = _host_for_engine(engine)
    explicit_port = _explicit_browser_port(engine)
    if explicit_port:
        if _engine_up(explicit_port, host=host):
            return explicit_port
        output_error(f"Configured browser port is not available on {host}:{explicit_port}")
        raise typer.Exit(1) from None
    if engine == "lightpanda":
        if _engine_up(9223, host=host):
            return 9223
        if _engine_up(9222, host=host):
            return 9222
        output_error(f"No browser engines available on {host}")
        raise typer.Exit(1) from None
    if engine == "chrome":
        if _engine_up(9222, host=host):
            return 9222
        if _engine_up(9223, host=host):
            return 9223
        output_error(f"No browser engines available on {host}")
        raise typer.Exit(1) from None
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
    return browser_support.agent_browser_reaper(configured, command_file=Path(__file__))


def _run_browser_reaper() -> None:
    reaper = _agent_browser_reaper()
    if Path(reaper).exists():
        subprocess.run(["node", reaper], text=True, capture_output=True, check=False)


def _with_default_session(args: list[str]) -> list[str]:
    if _has_session_arg(args) or os.environ.get("AGENT_BROWSER_SESSION", "").strip():
        return args
    return ["--session", _default_browser_session(), *args]


def _parse_engine_args(args: list[str]) -> tuple[str | None, list[str]]:
    engine = os.environ.get("ST_BROWSER_ENGINE", "").strip() or None
    engine, remaining, error = browser_support.parse_engine_args(args, initial_engine=engine)
    if error:
        output_error(error)
        raise typer.Exit(2) from None
    return engine, remaining


def _print_health() -> None:
    try:
        endpoint = _resolve_endpoint()
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


def _browser_check(args: list[str]) -> int:
    return browser_check.run_browser_check(
        args,
        output_error=output_error,
        resolve_browser_location=resolve_browser_location,
        select_port=_select_port,
        host_for_engine=_host_for_engine,
        cdp_ws=_cdp_ws,
        run_agent=_run_agent,
        run_browser_reaper=_run_browser_reaper,
        current_root=current_root,
        write_details=write_details,
        display_path=display_path,
        summary_hint=summary_hint,
        browser_route_error=BrowserRouteError,
    )


def _browser_update() -> int:
    current = _run_agent(["--version"], capture=True).stdout.strip() or "unknown"
    latest = subprocess.run(["npm", "view", "agent-browser", "version"], text=True, capture_output=True, check=False)
    print(f"agent-browser: installed={current} latest={latest.stdout.strip() or '?'}")
    print("Runtime:")
    try:
        endpoint = _resolve_endpoint()
        print(f"  host: {endpoint.host}")
        print(f"  source: {endpoint.source}")
        print(f"  debug_local: {endpoint.debug_local}")
    except BrowserTargetError as exc:
        print(f"  host: unavailable ({exc})")
    print(f"  agent-browser-bin: {_agent_browser_bin()}")
    return 0


def _browser_endpoint(args: list[str], engine: str | None) -> int:
    output_format = "http"
    if args:
        if args[0] in {"--ws", "ws"}:
            output_format = "ws"
        elif args[0] in {"--http", "http"}:
            output_format = "http"
        elif args[0] in {"--json", "json"}:
            output_format = "json"
        elif args[0] == "--format" and len(args) >= 2:
            output_format = args[1]
        else:
            output_error("Usage: st browser endpoint [--http|--ws|--json|--format http|ws|json]")
            return 2
    if output_format not in {"http", "ws", "json"}:
        output_error("Browser endpoint format must be http, ws, or json")
        return 2

    port = _select_port(engine)
    host = _host_for_engine(engine)
    http_url = f"http://{host}:{port}"
    ws_url = _cdp_ws(port, host=host)
    if not ws_url:
        output_error(f"Unable to resolve browser CDP endpoint on {host}:{port}")
        return 1
    if output_format == "ws":
        print(ws_url)
    elif output_format == "json":
        print(json.dumps({"engine": engine or "auto", "host": host, "port": port, "http": http_url, "ws": ws_url}))
    else:
        print(http_url)
    return 0


def _browser_url(args: list[str]) -> int:
    if not args:
        output_error("Usage: st browser url <project-or-url>")
        return 2
    try:
        route = resolve_browser_project_route(args[0])
    except BrowserRouteError as exc:
        output_error(str(exc))
        return 2
    print(f"{route.url} # {route.project_id} {route.source}")
    return 0


def _with_resolved_navigation_target(args: list[str], command: str) -> list[str]:
    if command not in {"open", "goto", "navigate"}:
        return args
    try:
        index = args.index(command)
    except ValueError:
        return args
    if index + 1 >= len(args):
        return args
    resolved = [*args]
    try:
        resolved[index + 1] = resolve_browser_location(resolved[index + 1])
    except BrowserRouteError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    return resolved


_USAGE = """Remote browser automation through st

Default target:
  Plain st browser commands use approved browser VM 100 via st vm ip.
  Override with ST_BROWSER_HOST, ST_BROWSER_DEFAULT_HOST, or ST_BROWSER_VM_ID.
  Do not start Chrome, CDP proxies, or agent-browser on the project/server host.
  Set ST_BROWSER_DISABLE_DEFAULT_VM_HOST=1 to require explicit host config.

Usage:
  st browser health
  st browser url <project>
  st browser check [--session <name>] <project-or-url> [screenshot-path]
  st browser open <project-or-url>
  st browser screenshot [path]
  st browser snapshot
  st browser eval <js>
  st browser endpoint [--http|--ws|--json]
  st browser update
  st browser [--chrome|--lp|--engine <name>] <agent-browser command> [args...]

Examples:
  st browser health
  st browser url a-term
  st browser check a-term /tmp/a-term.png
  st browser endpoint --ws
  st vm status <browser-vm-id>
  ST_BROWSER_HOST=<browser-vm-or-connector> st browser health
  ST_BROWSER_HOST=<browser-vm-or-connector> st browser check http://localhost:3001 /tmp/page.png

Debug local override:
  ST_BROWSER_HOST=127.0.0.1 ST_BROWSER_ALLOW_LOCAL=1 st browser health
"""


@app.callback(invoke_without_command=True)
@usage(
    surface="st.browser",
    cmd="st browser check <url> <png>",
    when="UI render verification; screenshots; DOM snapshots",
    precautions=(
        "use plain st browser; it auto-resolves approved browser VM 100",
        "never start chrome/CDP/agent-browser on project or server host by default",
        "only set ST_BROWSER_HOST / ST_BROWSER_VM_ID for explicit approved override",
    ),
    task_types=("frontend", "ui-design", "design-review", "verification"),
    tier="mandate",
)
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
        typer.echo(_USAGE)
        raise typer.Exit(0)
    if len(args) > 1 and args[1] in {"-h", "--help", "help"}:
        typer.echo(_USAGE)
        raise typer.Exit(0)
    engine, browser_args = _parse_engine_args(args)
    command = _agent_command(browser_args)
    if command == "health":
        _print_health()
        raise typer.Exit(0)
    if command == "url":
        raise typer.Exit(_browser_url(browser_args[1:]))
    if command == "check":
        raise typer.Exit(_browser_check(browser_args[1:]))
    if command == "endpoint":
        raise typer.Exit(_browser_endpoint(browser_args[1:], engine))
    if command == "update":
        raise typer.Exit(_browser_update())

    port = _select_port(engine)
    host = _host_for_engine(engine)
    ws = _cdp_ws(port, host=host)
    if not ws:
        output_error(f"Unable to resolve browser CDP endpoint on {host}:{port}")
        raise typer.Exit(1) from None
    scoped_browser_args = _with_default_session(_with_resolved_navigation_target(browser_args, command))
    if command == "open" and os.environ.get("ST_BROWSER_DISABLE_DEFAULT_VIEWPORT") != "1":
        _run_agent(
            [
                *_session_args(scoped_browser_args),
                "set",
                "viewport",
                os.environ.get("ST_BROWSER_VIEWPORT_WIDTH", "1600"),
                os.environ.get("ST_BROWSER_VIEWPORT_HEIGHT", "900"),
            ],
            cdp=ws,
        )
    result = _run_agent(scoped_browser_args, cdp=ws, capture=True)
    emit_result_or_details(current_root(), f"browser-{command or 'command'}", "BROWSER", result)
    _run_browser_reaper()
    if command not in {"open", "goto", "navigate"}:
        _close_blank_browser_targets(host, port)
    raise typer.Exit(result.returncode)
