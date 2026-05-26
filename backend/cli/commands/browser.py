"""Canonical browser automation command surface."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from hashlib import sha1
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

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

_HELP_ARGS = {"-h", "--help", "help"}
_NAVIGATION_COMMANDS = {"open", "goto", "navigate"}
_ENDPOINT_FORMATS = {"http", "ws", "json"}
_DEFAULT_VIEWPORT_WIDTH = "1600"
_DEFAULT_VIEWPORT_HEIGHT = "900"
_LOCAL_AI_FLAG = "--local-ai"
_LOCAL_AI_COMMAND = "local-ai"
_PROXMOX_FLAG = "--proxmox"
_PROXMOX_COMMAND = "proxmox"
_LOCAL_AI_PROFILE_ENV = "ST_BROWSER_LOCAL_AI_PROFILE"
_LOCAL_AI_CHROME_ENV = "ST_BROWSER_LOCAL_CHROME"
_DEFAULT_LOCAL_AI_PROFILE = "AI"
_LOCAL_CHROME_CANDIDATES = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
_ENDPOINT_ERROR_TEMPLATE = "Unable to resolve browser CDP endpoint on {host}:{port}"
_NO_ENGINES_TEMPLATE = "No browser engines available on {host}"
_CONFIGURED_PORT_UNAVAILABLE_TEMPLATE = "Configured browser port is not available on {host}:{port}"
_ENDPOINT_USAGE = "Usage: st browser endpoint [--http|--ws|--json|--format http|ws|json]"
_URL_USAGE = "Usage: st browser url <project-or-url>"
_LOCAL_URL_CONFIRM_ENV = "ST_BROWSER_CONFIRM_LOCAL_URL"


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


def _port_candidates(engine: str | None) -> tuple[int, ...]:
    if engine == "lightpanda":
        return (9223, 9222)
    if engine == "chrome":
        return (9222, 9223)
    return (9222, 9223)



def _select_port(engine: str | None) -> int:
    host = _host_for_engine(engine)
    explicit_port = _explicit_browser_port(engine)
    if explicit_port:
        if _engine_up(explicit_port, host=host):
            return explicit_port
        output_error(_CONFIGURED_PORT_UNAVAILABLE_TEMPLATE.format(host=host, port=explicit_port))
        raise typer.Exit(1) from None
    for port in _port_candidates(engine):
        if _engine_up(port, host=host):
            return port
    output_error(_NO_ENGINES_TEMPLATE.format(host=host))
    raise typer.Exit(1) from None


def _url_hostname(value: str) -> str | None:
    try:
        hostname = urlsplit(value.strip()).hostname
    except ValueError:
        return None
    return hostname.lower().rstrip(".") if hostname else None


def _is_local_browser_url(value: str) -> bool:
    hostname = _url_hostname(value)
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def _local_url_display_host(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        hostname = parsed.hostname or "unknown"
        try:
            port = parsed.port
        except ValueError:
            port = None
    except ValueError:
        return "unknown"
    return f"{hostname}:{port}" if port else hostname


def _local_url_confirmation_token(value: str) -> str:
    host = _local_url_display_host(value)
    return sha1(f"st-browser-local-url:{host}".encode()).hexdigest()[:8]


def _local_browser_url_error(value: str) -> str | None:
    if not _is_local_browser_url(value):
        return None
    token = _local_url_confirmation_token(value)
    if os.environ.get(_LOCAL_URL_CONFIRM_ENV, "").strip() == token:
        return None
    host = _local_url_display_host(value)
    return (
        f"LOCAL_BROWSER_URL_BLOCKED target_host={host}: st browser runs from browser VM "
        f"{_DEFAULT_BROWSER_VM_ID} by default; localhost/127.0.0.1 is that VM, not this server. "
        f"Use `st browser url <project>` or a reachable LAN/prod URL. "
        f"To confirm intentional local target: {_LOCAL_URL_CONFIRM_ENV}={token}"
    )


def _resolve_guarded_browser_location(value: str) -> str:
    resolved = resolve_browser_location(value)
    if message := _local_browser_url_error(resolved):
        raise BrowserRouteError(message)
    return resolved


def _run_agent(args: list[str], *, cdp: str | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    command = [_agent_browser_bin()]
    if cdp:
        command.extend(["--cdp", cdp])
    command.extend(args)
    return subprocess.run(command, text=True, capture_output=capture, check=False)


def _parse_browser_target_args(args: list[str]) -> tuple[str, list[str]]:
    target = os.environ.get("ST_BROWSER_TARGET", "").strip().lower() or "local-ai"
    if os.environ.get("ST_BROWSER_LOCAL_AI", "").strip() == "1":
        target = "local-ai"
    if os.environ.get("ST_BROWSER_FORCE_PROXMOX", "").strip() == "1":
        target = "proxmox"
    remaining: list[str] = []
    for index, arg in enumerate(args):
        if arg == _LOCAL_AI_FLAG or (index == 0 and arg == _LOCAL_AI_COMMAND):
            target = "local-ai"
            continue
        if arg == _PROXMOX_FLAG or (index == 0 and arg == _PROXMOX_COMMAND):
            target = "proxmox"
            continue
        remaining.append(arg)
    if target in {"vm", "browser-vm", "remote"}:
        target = "proxmox"
    if target not in {"local-ai", "proxmox"}:
        target = "local-ai"
    return target, remaining


def _agent_command_index(args: list[str]) -> int | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return index
        if arg in _AGENT_BROWSER_OPTIONS_WITH_VALUE:
            index += 2
        else:
            index += 1
    return None


def _has_agent_option(args: list[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def _system_chrome_path() -> str:
    configured = os.environ.get(_LOCAL_AI_CHROME_ENV, "").strip()
    if configured:
        return configured
    for candidate in _LOCAL_CHROME_CANDIDATES:
        if path := shutil.which(candidate):
            return path
    return ""


def _local_ai_agent_args(args: list[str]) -> list[str]:
    prefix: list[str] = []
    if not _has_agent_option(args, "--profile") and not os.environ.get("AGENT_BROWSER_PROFILE", "").strip():
        prefix.extend(["--profile", os.environ.get(_LOCAL_AI_PROFILE_ENV, "").strip() or _DEFAULT_LOCAL_AI_PROFILE])
    if not _has_agent_option(args, "--executable-path") and not os.environ.get(
        "AGENT_BROWSER_EXECUTABLE_PATH", ""
    ).strip():
        chrome = _system_chrome_path()
        if not chrome:
            output_error(
                "Local system Chrome not found; set ST_BROWSER_LOCAL_CHROME or use plain st browser for the VM target"
            )
            raise typer.Exit(1) from None
        prefix.extend(["--executable-path", chrome])
    if (
        os.environ.get("ST_BROWSER_LOCAL_AI_HEADLESS", "").strip() != "1"
        and not _has_agent_option(args, "--headed")
        and not os.environ.get("AGENT_BROWSER_HEADED", "").strip()
    ):
        prefix.append("--headed")
    return [*prefix, *args]


def _print_local_ai_health() -> None:
    print("Target: local system Chrome (AI profile)")
    print(f"chrome: {_system_chrome_path() or 'not found'}")
    print(f"profile: {os.environ.get(_LOCAL_AI_PROFILE_ENV, '').strip() or _DEFAULT_LOCAL_AI_PROFILE}")
    print(f"agent-browser-bin: {_agent_browser_bin()}")


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
        resolve_browser_location=_resolve_guarded_browser_location,
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


def _print_runtime_details() -> None:
    print("Runtime:")
    try:
        endpoint = _resolve_endpoint()
        print(f"  host: {endpoint.host}")
        print(f"  source: {endpoint.source}")
        print(f"  debug_local: {endpoint.debug_local}")
    except BrowserTargetError as exc:
        print(f"  host: unavailable ({exc})")
    print(f"  agent-browser-bin: {_agent_browser_bin()}")



def _browser_update() -> int:
    current = _run_agent(["--version"], capture=True).stdout.strip() or "unknown"
    latest = subprocess.run(["npm", "view", "agent-browser", "version"], text=True, capture_output=True, check=False)
    print(f"agent-browser: installed={current} latest={latest.stdout.strip() or '?'}")
    _print_runtime_details()
    return 0


def _parse_endpoint_format(args: list[str]) -> str | None:
    if not args:
        return "http"
    first = args[0]
    if first in {"--ws", "ws"}:
        return "ws"
    if first in {"--http", "http"}:
        return "http"
    if first in {"--json", "json"}:
        return "json"
    if first == "--format" and len(args) >= 2:
        return args[1]
    return None



def _print_endpoint(output_format: str, *, engine: str | None, host: str, port: int, ws_url: str) -> None:
    http_url = f"http://{host}:{port}"
    if output_format == "ws":
        print(ws_url)
        return
    if output_format == "json":
        print(json.dumps({"engine": engine or "auto", "host": host, "port": port, "http": http_url, "ws": ws_url}))
        return
    print(http_url)



def _browser_endpoint(args: list[str], engine: str | None) -> int:
    output_format = _parse_endpoint_format(args)
    if output_format is None:
        output_error(_ENDPOINT_USAGE)
        return 2
    if output_format not in _ENDPOINT_FORMATS:
        output_error("Browser endpoint format must be http, ws, or json")
        return 2

    port = _select_port(engine)
    host = _host_for_engine(engine)
    ws_url = _cdp_ws(port, host=host)
    if not ws_url:
        output_error(_ENDPOINT_ERROR_TEMPLATE.format(host=host, port=port))
        return 1
    _print_endpoint(output_format, engine=engine, host=host, port=port, ws_url=ws_url)
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


def _with_resolved_navigation_target(args: list[str], command: str) -> list[str]:
    if command not in _NAVIGATION_COMMANDS:
        return args
    try:
        index = args.index(command)
    except ValueError:
        return args
    if index + 1 >= len(args):
        return args
    resolved = [*args]
    try:
        resolved[index + 1] = _resolve_guarded_browser_location(resolved[index + 1])
    except BrowserRouteError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    return resolved


def _with_resolved_local_navigation_target(args: list[str], command: str) -> list[str]:
    if command not in _NAVIGATION_COMMANDS:
        return args
    index = _agent_command_index(args)
    if index is None or index + 1 >= len(args):
        return args
    resolved = [*args]
    try:
        resolved[index + 1] = resolve_browser_location(resolved[index + 1])
    except BrowserRouteError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    return resolved


def _run_local_ai_agent(args: list[str]) -> subprocess.CompletedProcess[str]:
    return _run_agent(_local_ai_agent_args(args), capture=True)


def _local_agent_failure(label: str, result: subprocess.CompletedProcess[str]) -> str | None:
    if result.returncode == 0:
        return None
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return f"{label}: rc={result.returncode} hint={summary_hint(output) if output else '-'}"


def _local_check_viewports(screenshot_path: str) -> list[tuple[str, int, int, str]]:
    viewports = [
        (
            "desktop",
            int(os.environ.get("ST_BROWSER_CHECK_DESKTOP_WIDTH", "1600")),
            int(os.environ.get("ST_BROWSER_CHECK_DESKTOP_HEIGHT", "900")),
            screenshot_path,
        ),
        (
            "narrow",
            int(os.environ.get("ST_BROWSER_CHECK_NARROW_WIDTH", "1180")),
            int(os.environ.get("ST_BROWSER_CHECK_NARROW_HEIGHT", "900")),
            _suffixed(screenshot_path, "-narrow"),
        ),
        (
            "mobile",
            int(os.environ.get("ST_BROWSER_CHECK_MOBILE_WIDTH", "390")),
            int(os.environ.get("ST_BROWSER_CHECK_MOBILE_HEIGHT", "844")),
            _suffixed(screenshot_path, "-mobile"),
        ),
    ]
    return viewports[:1] if os.environ.get("ST_BROWSER_CHECK_RESPONSIVE") == "0" else viewports


def _local_check_items(parsed: dict[str, object] | list[object], key: str) -> list[object]:
    if not isinstance(parsed, dict):
        return []
    value = parsed.get(key)
    return list(value) if isinstance(value, list) else []


def _browser_local_ai_check(args: list[str]) -> int:
    session = None
    if args[:1] == ["--session"]:
        if len(args) < 2:
            output_error("--session requires a name")
            return 2
        session = args[1]
        args = args[2:]
    if not args:
        output_error("Usage: st browser --local-ai check [--session <name>] <url> [screenshot-path]")
        return 2
    try:
        url = resolve_browser_location(args[0])
    except BrowserRouteError as exc:
        output_error(str(exc))
        return 2
    screenshot_path = args[1] if len(args) > 1 else "/tmp/st-browser-local-ai-check.png"
    session_args = ["--session", session or f"st-browser-local-ai-check-{os.getpid()}-{time.time_ns()}"]
    command_warnings: list[str] = []
    error_result = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    network_result = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
    viewports = _local_check_viewports(screenshot_path)
    try:
        first_viewport = _run_local_ai_agent(
            [*session_args, "set", "viewport", str(viewports[0][1]), str(viewports[0][2])]
        )
        if warning := _local_agent_failure("initial viewport", first_viewport):
            command_warnings.append(warning)
        open_result = _run_local_ai_agent([*session_args, "open", url])
        if open_result.returncode != 0:
            if warning := _local_agent_failure("open", open_result):
                output_error(warning)
            return open_result.returncode
        load_wait = _run_local_ai_agent([*session_args, "wait", os.environ.get("ST_BROWSER_CHECK_WAIT", "5000")])
        if warning := _local_agent_failure("load wait", load_wait):
            command_warnings.append(warning)
        hook_result = _run_local_ai_agent(
            [
                *session_args,
                "eval",
                "window.__sfErrors=[];window.__sfWarnings=[];"
                "const oe=console.error;console.error=(...a)=>{window.__sfErrors.push(a.map(String).join(' '));oe.apply(console,a)};"
                "const ow=console.warn;console.warn=(...a)=>{window.__sfWarnings.push(a.map(String).join(' '));ow.apply(console,a)};'capturing'",
            ]
        )
        if warning := _local_agent_failure("console hook", hook_result):
            command_warnings.append(warning)
        settle = _run_local_ai_agent([*session_args, "wait", "2000"])
        if warning := _local_agent_failure("settle wait", settle):
            command_warnings.append(warning)

        for label, width, height, path in viewports:
            viewport = _run_local_ai_agent([*session_args, "set", "viewport", str(width), str(height)])
            if warning := _local_agent_failure(f"{label} viewport", viewport):
                command_warnings.append(warning)
            viewport_wait = _run_local_ai_agent(
                [*session_args, "wait", os.environ.get("ST_BROWSER_CHECK_VIEWPORT_SETTLE_MS", "350")]
            )
            if warning := _local_agent_failure(f"{label} wait", viewport_wait):
                command_warnings.append(warning)
            screenshot = _run_local_ai_agent([*session_args, "screenshot", path])
            if warning := _local_agent_failure(f"{label} screenshot", screenshot):
                command_warnings.append(warning)
        error_result = _run_local_ai_agent(
            [
                *session_args,
                "eval",
                "JSON.stringify({errors:window.__sfErrors||[],warnings:window.__sfWarnings||[],url:location.href,title:document.title})",
            ]
        )
        if warning := _local_agent_failure("console read", error_result):
            command_warnings.append(warning)
        network_result = _run_local_ai_agent(
            [
                *session_args,
                "eval",
                "JSON.stringify(performance.getEntriesByType('resource').filter(e=>e.responseStatus>=400).map(e=>e.responseStatus+' '+e.name.split('/').pop()))",
            ]
        )
        if warning := _local_agent_failure("network read", network_result):
            command_warnings.append(warning)
    finally:
        close_result = _run_local_ai_agent([*session_args, "close"])
        if warning := _local_agent_failure("close", close_result):
            command_warnings.append(warning)

    detail_lines = [
        "Target: local-ai",
        f"Screenshot: {screenshot_path}",
        "Responsive set: " + ", ".join(f"{label} {width}x{height}" for label, width, height, _ in viewports),
    ]
    if len(viewports) > 1:
        detail_lines.append("Additional screenshots:")
        for label, _, _, path in viewports[1:]:
            detail_lines.append(f"  {label}: {path}")
    errors = _json_from_agent_eval(error_result.stdout)
    network = _json_from_agent_eval(network_result.stdout)
    error_items = _local_check_items(errors, "errors")
    warning_items = _local_check_items(errors, "warnings")
    network_items = list(network) if isinstance(network, list) else []
    if isinstance(errors, dict):
        detail_lines.append(f"Page: {errors.get('url', 'unknown')}")
        detail_lines.append(f"Title: {errors.get('title', 'unknown')}")
    if error_items:
        detail_lines.append(f"\nConsole errors ({len(error_items)}):")
        detail_lines.extend(str(item) for item in error_items)
    if warning_items:
        detail_lines.append(f"\nConsole warnings ({len(warning_items)}):")
        detail_lines.extend(str(item) for item in warning_items)
    if network_items:
        detail_lines.append(f"\nFailed network requests ({len(network_items)}):")
        detail_lines.extend(str(item) for item in network_items)
    if command_warnings:
        detail_lines.append(f"\nBrowser command warnings ({len(command_warnings)}):")
        detail_lines.extend(command_warnings)
    root = current_root()
    details = write_details(root, "browser-check-local-ai", "\n".join(detail_lines))
    status = "OK" if not error_items and not warning_items and not network_items else "ISSUES"
    print(
        f"BROWSER_CHECK:{status}|target=local-ai|errors={len(error_items)}|warnings={len(warning_items)}|"
        f"network={len(network_items)}|command_warnings={len(command_warnings)}|"
        f"screenshot={screenshot_path}|details:{display_path(root, details)}"
    )
    return 0


def _run_local_ai_browser_command(command: str, browser_args: list[str]) -> int:
    if command == "health":
        _print_local_ai_health()
        return 0
    if command == "url":
        index = _agent_command_index(browser_args)
        return _browser_url(browser_args[index + 1 :] if index is not None else [])
    if command == "endpoint":
        output_error("st browser endpoint targets Proxmox/VM CDP; rerun with `st browser --proxmox endpoint`")
        return 2
    if command == "update":
        return _browser_update()
    if command == "check":
        index = _agent_command_index(browser_args)
        return _browser_local_ai_check(browser_args[index + 1 :] if index is not None else [])
    if not command:
        output_error("Usage: st browser --local-ai <agent-browser command> [args...]")
        return 2
    resolved_browser_args = _with_resolved_local_navigation_target(browser_args, command)
    result = _run_agent(_local_ai_agent_args(resolved_browser_args), capture=True)
    emit_result_or_details(current_root(), f"browser-local-ai-{command or 'command'}", "BROWSER", result)
    return result.returncode


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
  Default mode uses system Chrome, profile `AI`, and headed mode.
  Override local Chrome with ST_BROWSER_LOCAL_CHROME, ST_BROWSER_LOCAL_AI_PROFILE,
  or ST_BROWSER_LOCAL_AI_HEADLESS=1.

Local desktop UI:
  Use st ui when the already-open desktop/PWA is the right evidence source or browser automation is not enough.
"""


def _show_usage_and_exit() -> None:
    typer.echo(_USAGE)
    raise typer.Exit(0)



def _wants_help(args: list[str]) -> bool:
    return not args or args[0] in _HELP_ARGS or (len(args) > 1 and args[1] in _HELP_ARGS)



def _handle_builtin_command(command: str, browser_args: list[str], engine: str | None) -> int | None:
    if command == "health":
        _print_health()
        return 0
    if command == "url":
        return _browser_url(browser_args[1:])
    if command == "check":
        return _browser_check(browser_args[1:])
    if command == "endpoint":
        return _browser_endpoint(browser_args[1:], engine)
    if command == "update":
        return _browser_update()
    return None



def _viewport_args(scoped_browser_args: list[str]) -> list[str]:
    return [
        *_session_args(scoped_browser_args),
        "set",
        "viewport",
        os.environ.get("ST_BROWSER_VIEWPORT_WIDTH", _DEFAULT_VIEWPORT_WIDTH),
        os.environ.get("ST_BROWSER_VIEWPORT_HEIGHT", _DEFAULT_VIEWPORT_HEIGHT),
    ]



def _run_browser_command(command: str, browser_args: list[str], *, engine: str | None) -> int:
    resolved_browser_args = _with_resolved_navigation_target(browser_args, command)
    port = _select_port(engine)
    host = _host_for_engine(engine)
    ws = _cdp_ws(port, host=host)
    if not ws:
        output_error(_ENDPOINT_ERROR_TEMPLATE.format(host=host, port=port))
        return 1
    scoped_browser_args = _with_default_session(resolved_browser_args)
    if command == "open" and os.environ.get("ST_BROWSER_DISABLE_DEFAULT_VIEWPORT") != "1":
        _run_agent(_viewport_args(scoped_browser_args), cdp=ws)
    result = _run_agent(scoped_browser_args, cdp=ws, capture=True)
    emit_result_or_details(current_root(), f"browser-{command or 'command'}", "BROWSER", result)
    _run_browser_reaper()
    if command not in _NAVIGATION_COMMANDS:
        _close_blank_browser_targets(host, port)
    return result.returncode


@app.callback(invoke_without_command=True)
@usage(
    surface="st.browser",
    cmd="st browser check <url> <png>",
    when="UI render verification; screenshots; DOM snapshots",
    precautions=(
        "plain st browser uses local Chrome AI profile by default",
        "use --proxmox or ST_BROWSER_TARGET=proxmox when VM isolation is better for the task",
        "use st ui when the open desktop/PWA is the right evidence source",
        "never start arbitrary chrome/CDP on project or server host; local-AI is the approved local profile flow",
        "only set ST_BROWSER_HOST / ST_BROWSER_VM_ID for explicit approved override",
    ),
    task_types=("frontend", "ui-design", "design-review", "verification"),
    tier="mandate",
)
def browser(ctx: typer.Context) -> None:
    """Run browser health, checks, screenshots, snapshots, or DOM commands.

    Examples:
      st browser health
      st browser check summitflow /tmp/summitflow.png
    """
    if ctx.invoked_subcommand is not None:
        return
    args = list(ctx.args)
    if _wants_help(args):
        _show_usage_and_exit()
    target, args = _parse_browser_target_args(args)
    engine, browser_args = _parse_engine_args(args)
    command = _agent_command(browser_args)
    if target == "local-ai":
        raise typer.Exit(_run_local_ai_browser_command(command, browser_args))
    builtin_result = _handle_builtin_command(command, browser_args, engine)
    if builtin_result is not None:
        raise typer.Exit(builtin_result)
    raise typer.Exit(_run_browser_command(command, browser_args, engine=engine))
