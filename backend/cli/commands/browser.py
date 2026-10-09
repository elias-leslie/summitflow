"""SummitFlow browser policy adapter for the supported owner executable."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

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
_STRUCTURED_OPERATIONS = {"capabilities", "help", "observe", "run", "extract", "session", "workflow", "selected-tabs"}
_HOST_COMMANDS = {"check", "health", "update", "inventory", "reap-isolated", "url", "endpoint", "session", "workflow"}

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
        prefix = browser_policy.local_agent_prefix(args)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None
    return [*prefix, *args]


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
    command_index = browser_policy.command_index(args)
    if command_index is None:
        return args
    resolved = [*args]
    positional = []
    index = command_index + 1
    value_options = _AGENT_BROWSER_OPTIONS_WITH_VALUE | {"--threshold", "--selector"}
    while index < len(resolved):
        option, separator, value = resolved[index].partition("=")
        if option in value_options:
            if not separator:
                index += 1
                if index == len(resolved):
                    break  # Missing command values remain subject to owner validation.
                value = resolved[index]
            if option == "--screenshot-dir" and value:
                path = _absolute_local_output_path(value)
                resolved[index] = f"{option}={path}" if separator else path
        elif not resolved[index].startswith("-"):
            positional.append(index)
        index += 1
    if positional:
        # Core accepts [selector] [path]. With two operands the first is a
        # selector; a lone explicit ref/CSS selector keeps the generated path.
        path_index = positional[-1]
        operand = resolved[path_index]
        selector_only = len(positional) == 1 and (
            operand.startswith(("@", "#", "[", "css=", "xpath=", "text="))
            or (operand.startswith(".") and not operand.startswith(("./", "../")) and Path(operand).suffix.lower() not in {".png", ".jpeg", ".jpg", ".webp"})
        )
        if not selector_only:
            resolved[path_index] = _absolute_local_output_path(operand)
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
    try:
        session_args, args = browser_support.split_session_options(args)
        selected = None
        positional = []
        index = 0
        while index < len(args):
            arg = args[index]
            if arg == "--viewports" or arg.startswith("--viewports="):
                if selected is not None:
                    raise ValueError("--viewports may be supplied only once")
                if arg == "--viewports":
                    index += 1
                    if index == len(args):
                        raise ValueError("--viewports requires a comma-separated subset of desktop,narrow,mobile")
                    value = args[index]
                else:
                    value = arg.split("=", 1)[1]
                selected = value.split(",")
                if not selected or len(set(selected)) != len(selected) or set(selected) - {"desktop", "narrow", "mobile"}:
                    raise ValueError("--viewports requires a comma-separated subset of desktop,narrow,mobile")
            elif arg.startswith("-"):
                raise ValueError(f"Unknown browser check option: {arg}")
            else:
                positional.append(arg)
            index += 1
        if not 1 <= len(positional) <= 2:
            raise ValueError("check requires a URL and at most one screenshot path")
    except ValueError as exc:
        output_error(str(exc))
        output_error(f"Usage: st browser {'--local-ai ' if target == 'local-ai' else ''}check [--session <name>] <url> [screenshot-path]")
        raise typer.Exit(2) from None
    try:
        url = resolve_browser_location(positional[0]) if target == "local-ai" else _resolve_guarded_browser_location(positional[0])
    except BrowserRouteError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    session = session_args[1] if session_args else f"st-check-{uuid4().hex[:12]}"
    screenshot = positional[1] if len(positional) > 1 else f"/tmp/st-browser-check-{uuid4().hex[:12]}.png"
    if target == "local-ai":
        screenshot = _absolute_local_output_path(screenshot)
    viewports = [
        {"label": "desktop", "width": int(os.environ.get("ST_BROWSER_CHECK_DESKTOP_WIDTH", "1600")), "height": int(os.environ.get("ST_BROWSER_CHECK_DESKTOP_HEIGHT", "900")), "path": screenshot},
        {"label": "narrow", "width": int(os.environ.get("ST_BROWSER_CHECK_NARROW_WIDTH", "1180")), "height": int(os.environ.get("ST_BROWSER_CHECK_NARROW_HEIGHT", "900")), "path": _suffixed(screenshot, "-narrow")},
        {"label": "mobile", "width": int(os.environ.get("ST_BROWSER_CHECK_MOBILE_WIDTH", "390")), "height": int(os.environ.get("ST_BROWSER_CHECK_MOBILE_HEIGHT", "844")), "path": _suffixed(screenshot, "-mobile")},
    ]
    if selected is not None:
        viewports = [row for row in viewports if row["label"] in selected]
    elif os.environ.get("ST_BROWSER_CHECK_RESPONSIVE") == "0":
        viewports = viewports[:1]
    return ["--session", session, "check", url, screenshot], {
        "url": url, "screenshot_path": screenshot, "session": session, "viewports": viewports,
        "settle_ms": os.environ.get("ST_BROWSER_CHECK_SETTLE_MS", "500"),
        "viewport_settle_ms": os.environ.get("ST_BROWSER_CHECK_VIEWPORT_SETTLE_MS", "350"),
    }


def focused_help_requested(argv: list[str]) -> bool:
    """Identify owner command help without resolving a project or executable."""
    _, args = _parse_browser_target_args(argv)
    _, args = _parse_engine_args(args)
    command = _agent_command(args)
    return bool(command and (command not in _HOST_COMMANDS or command in _STRUCTURED_OPERATIONS) and any(arg in {"--help", "-h"} for arg in args))


def _structured_payload(command: str, tail: list[str]) -> tuple[str, dict[str, object]]:
    if any(arg in {"--help", "-h"} for arg in tail):
        path = [command, *tail[:next(index for index, arg in enumerate(tail) if arg in {"--help", "-h"})]]
        if any(arg.startswith("-") for arg in path):
            raise ValueError("focused help accepts only the core command path")
        return "help", {"command": path}
    if command == "capabilities":
        if len(tail) > 1 or any(arg.startswith("-") for arg in tail):
            raise ValueError("Usage: st browser capabilities [topic]")
        return command, {"topic": tail[0]} if tail else {}
    if command == "help":
        if not tail or any(arg.startswith("-") for arg in tail):
            raise ValueError("Usage: st browser help <core-command> [subcommand...]")
        return command, {"command": tail}
    if command == "session":
        return command, browser_support.session_lifecycle_payload(tail)
    if command == "selected-tabs":
        return command, browser_support.selected_tabs_payload(tail)
    if command == "workflow":
        return command, browser_support.workflow_payload(tail)
    if command in {"run", "extract"}:
        options: dict[str, str] = {}
        index = 0
        while index < len(tail):
            arg, separator, value = tail[index].partition("=")
            if arg not in {"--file", "--max-chars"} or arg in options:
                raise ValueError(f"Usage: st browser {command} --file <JSON-path> [--max-chars N]")
            if not separator:
                index += 1
                if index == len(tail) or tail[index].startswith("-"):
                    raise ValueError(f"{arg} requires a value")
                value = tail[index]
            if not value:
                raise ValueError(f"{arg} requires a value")
            options[arg] = value
            index += 1
        if "--file" not in options:
            raise ValueError(f"Usage: st browser {command} --file <JSON-path> [--max-chars N]")
        budget = _structured_integer("--max-chars", options["--max-chars"]) if "--max-chars" in options else None
        payload = browser_support.read_structured_payload(options["--file"])
        if budget is not None:
            payload["max_chars"] = budget
        return command, payload
    if command == "step":
        step_payload: dict[str, object] = {}
        if tail and tail[0].split("=", 1)[0] == "--max-chars":
            arg, separator, value = tail[0].partition("=")
            consumed = 1 if separator else 2
            if not separator:
                value = tail[1] if len(tail) > 1 else ""
            step_payload["max_chars"] = _structured_integer(arg, value)
            tail = tail[consumed:]
        step_payload["actions"] = [browser_support.validate_structured_action(tail)]
        return "run", step_payload
    if command != "observe":
        raise ValueError("unsupported structured browser operation")
    payload: dict[str, object] = {"interactive": False, "compact": True, "delta": True, "full": False}
    index = 0
    seen = set()
    while index < len(tail):
        arg, separator, value = tail[index].partition("=")
        option_group = "compact" if arg in {"--compact", "--no-compact"} else "delta" if arg in {"--delta", "--no-delta"} else arg
        if option_group in seen:
            raise ValueError(f"Repeated observe option: {arg}")
        seen.add(option_group)
        if arg in {"--selector", "--screenshot", "--depth", "--max-chars"}:
            if not separator:
                index += 1
                if index == len(tail) or tail[index].startswith("-"):
                    raise ValueError(f"{arg} requires a value")
                value = tail[index]
            if not value:
                raise ValueError(f"{arg} requires a value")
            payload[arg[2:].replace("-", "_")] = _structured_integer(arg, value) if arg in {"--depth", "--max-chars"} else value
        elif arg == "--interactive" and not separator:
            payload["interactive"] = True
        elif arg == "--full" and not separator:
            payload["full"] = True
        elif arg in {"--compact", "--no-compact"} and not separator:
            payload["compact"] = arg == "--compact"
        elif arg in {"--delta", "--no-delta"} and not separator:
            payload["delta"] = arg == "--delta"
        else:
            raise ValueError(f"Unknown observe option: {tail[index]}")
        index += 1
    return command, payload


def _structured_integer(option: str, value: str) -> int:
    minimum = 0 if option == "--depth" else 1
    if not re.fullmatch(r"[0-9]+", value) or int(value) < minimum:
        label = "a nonnegative integer" if minimum == 0 else "a positive integer"
        raise ValueError(f"{option} requires {label}")
    return int(value)


def _resolve_payload_screenshots(payload: dict[str, object]) -> None:
    screenshot = payload.get("screenshot")
    if isinstance(screenshot, str) and screenshot:
        payload["screenshot"] = _absolute_local_output_path(screenshot)
    observation = payload.get("observation")
    if isinstance(observation, dict):
        _resolve_payload_screenshots(cast(dict[str, object], observation))


def _resolve_workflow_actions(payload: dict[str, object]) -> None:
    definition = payload.get("definition")
    if not isinstance(definition, dict):
        return
    steps = cast(dict[str, object], definition).get("steps")
    if not isinstance(steps, list):
        return  # The owner validates definition/schema completeness.
    parameters = cast(dict[str, object], payload["parameters"])

    def replace_parameter(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in parameters:
            raise ValueError(f"Unknown workflow parameter: {name}")
        value = parameters[name]
        if not isinstance(value, str | int | float | bool):
            raise ValueError("workflow parameters must be scalar values")
        return str(value)

    for step in steps:
        if not isinstance(step, dict):
            continue
        typed_step = cast(dict[str, object], step)
        if "actions" not in typed_step:
            continue
        actions = typed_step["actions"]
        if not isinstance(actions, list):
            raise ValueError("workflow step actions must be an array of arrays of strings")
        resolved_actions = []
        for action in actions:
            resolved = browser_support.validate_structured_action(action)
            if resolved[0] in _NAVIGATION_COMMANDS and len(resolved) > 1:
                resolved[1] = re.sub(r"\{\{([^{}]+)\}\}", replace_parameter, resolved[1])
            resolved = _with_navigation(resolved, resolved[0], guarded=False)
            resolved = _with_resolved_local_screenshot_path(resolved, resolved[0])
            resolved_actions.append(resolved)
        typed_step["actions"] = resolved_actions
        for artifact in (typed_step, typed_step.get("observation")):
            if isinstance(artifact, dict):
                typed_artifact = cast(dict[str, object], artifact)
                screenshot = typed_artifact.get("screenshot")
                if isinstance(screenshot, str):
                    typed_artifact["screenshot"] = re.sub(r"\{\{([^{}]+)\}\}", replace_parameter, screenshot)
        _resolve_payload_screenshots(typed_step)


def _build_structured_request(
    target: str, engine: str | None, browser_args: list[str], command: str,
    context: dict[str, Any], *, original_argv: list[str], selected_tab: str | None = None,
) -> tuple[dict[str, object], bool]:
    index = browser_policy.command_index(browser_args)
    assert index is not None
    try:
        prefix_session, prefix = browser_support.split_session_options(browser_args[:index])
        if prefix:
            raise ValueError("structured requests accept only host target, engine and session options before the command")
        tail = browser_args[index + 1:]
        if command == "step":
            # Target parsing is permissive for legacy commands. Never let it
            # remove embedded policy options from a structured action.
            tail = original_argv[original_argv.index("step") + 1:]
            session, operation_tail = prefix_session, tail
        else:
            session, operation_tail = browser_support.split_session_options([*prefix_session, *tail])
        operation, payload = _structured_payload(command, operation_tail)
        if operation == "selected-tabs":
            target = "selected-tab"
        browser_operation = operation in {"observe", "run", "extract", "workflow"}
        if not browser_operation and session:
            raise ValueError("capabilities/help/session lifecycle do not accept a browser session option")
        if operation == "session" and target != "local-ai":
            raise ValueError("Managed session lifecycle is available only for the local target")
        scoped = []
        managed_session = None
        if browser_operation:
            if target == "selected-tab" and (session or operation not in {"observe", "run", "extract"}):
                raise ValueError("Selected tabs support observe/run/extract and core actions; no session switching or workflows")
            managed_session = browser_policy.managed_session_name(session) if target == "local-ai" else None
            if operation == "workflow" and (target != "local-ai" or not managed_session):
                raise ValueError("workflow requires an explicit local managed --session NAME; create it with `st browser session create NAME`")
            scoped = ["--session", f"sel-{selected_tab}"] if target == "selected-tab" else (session if managed_session else _with_local_ai_session(session)) if target == "local-ai" else (
                session or ["--session", os.environ.get("AGENT_BROWSER_SESSION", "").strip() or _default_browser_session()]
            )
            binding = payload.get("binding")
            binding_session = cast(dict[str, object], binding).get("session") if isinstance(binding, dict) else None
            if isinstance(binding_session, str) and binding_session != scoped[1]:
                raise ValueError("binding session must match the host-selected browser session")
            if operation == "run" and "actions" in payload:
                actions = payload["actions"]
                if not isinstance(actions, list) or not actions:
                    raise ValueError("run actions must be a nonempty array of arrays of strings")
                resolved_actions = []
                for action in actions:
                    resolved = browser_support.validate_structured_action(action)
                    resolved = _with_navigation(resolved, resolved[0], guarded=target == "proxmox")
                    resolved = _with_resolved_local_screenshot_path(resolved, resolved[0])
                    resolved_actions.append(resolved)
                payload["actions"] = resolved_actions
            if operation == "workflow":
                _resolve_workflow_actions(payload)
            _resolve_payload_screenshots(payload)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    agent_bin = _agent_browser_bin() if browser_operation or operation in {"help", "session", "selected-tabs"} else "agent-browser"
    launch: dict[str, object]
    if target == "local-ai" and (browser_operation or operation == "session"):
        try:
            launch = (
                browser_policy.managed_session_launch(managed_session, agent_browser_bin=agent_bin)
                if managed_session or operation == "session" else browser_policy.local_launch(scoped, agent_browser_bin=agent_bin)
            )
        except ValueError as exc:
            output_error(str(exc))
            raise typer.Exit(1) from None
        endpoint = None
    else:
        launch = {"agent_browser_bin": agent_bin, "prefix": [], "window_mode": "remote" if browser_operation else "none", "default_launch": False, "minimize": False, "window_class": ""}
        if target == "selected-tab":
            launch["selected_tab"] = selected_tab
        endpoint = _endpoint_payload(engine, live=True) if browser_operation and target != "selected-tab" else None
    root = Path(context.get("project_root") or current_root()).resolve()
    return {
        "contract_version": 2, "operation": operation, "target": target, "command": operation,
        "args": scoped, "root": str(root), "endpoint": endpoint, "launch": launch,
        "check": None, "default_viewport": None,
        "reaper": "bundled" if target == "proxmox" else None, "payload": payload,
    }, target == "local-ai" and browser_operation and not managed_session


def _build_request(argv: list[str], context: dict[str, Any]) -> tuple[dict[str, object], bool]:
    try:
        selected_tab, selected_args = browser_support.selected_tab_options(argv)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(2) from None
    if selected_tab:
        index = browser_policy.command_index(selected_args)
        if index != 0:
            output_error("--selected-tab cannot combine with launch, engine, target or session options")
            raise typer.Exit(2)
        command = selected_args[0]
        if command in {"session", "check", "workflow", "capabilities", "help", "health", "inventory", "update", "reap-isolated", "url", "endpoint", "selected-tabs", "local-ai", "proxmox"} or focused_help_requested(selected_args):
            output_error("Selected tabs support observe/run/extract and core actions only; use unqualified discovery/help")
            raise typer.Exit(2)
        if command not in {"observe", "run", "extract", "step"}:
            selected_args = ["step", *selected_args]
            command = "step"
        return _build_structured_request("selected-tab", None, selected_args, command, context, original_argv=selected_args, selected_tab=selected_tab)
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
    if command in _STRUCTURED_OPERATIONS | {"step"} or focused_help_requested(argv):
        return _build_structured_request(target, engine, browser_args, command, context, original_argv=argv)
    operation = command if command in {"check", "health", "update", "inventory", "reap-isolated"} else "agent"
    if operation == "reap-isolated":
        index = browser_policy.command_index(browser_args)
        tail = browser_args[index + 1 :] if index is not None else []
        if target != "local-ai" or tail not in ([], ["--dry-run"]):
            output_error("Usage: st browser reap-isolated [--dry-run] (local target only)")
            raise typer.Exit(2)
        browser_args = tail
    if operation == "inventory":
        if target != "local-ai":
            output_error("Browser runtime inventory is available only for the local host")
            raise typer.Exit(2)
        index = browser_policy.command_index(browser_args)
        if index is None or browser_args[index + 1 :] not in ([], ["--json"]):
            output_error("Usage: st browser inventory [--json]")
            raise typer.Exit(2)
        browser_args = []
    agent_bin = "agent-browser" if target == "proxmox" and operation == "health" else _agent_browser_bin()
    check = None
    managed_session = None
    if operation == "check":
        index = browser_policy.command_index(browser_args)
        assert index is not None
        browser_args, check = _check_payload(target, [*browser_args[:index], *browser_args[index + 1:]])
    if target == "local-ai":
        if operation in {"update", "reap-isolated"}:
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
        if operation not in {"update", "reap-isolated"}:
            if operation not in {"health", "check", "inventory"}:
                try:
                    managed_session = browser_policy.managed_session_name(browser_args)
                except ValueError as exc:
                    output_error(str(exc))
                    raise typer.Exit(2) from None
                if managed_session:
                    try:
                        selected, core_args = browser_support.split_session_options(browser_args)
                        browser_args = [*selected, *browser_support.validate_structured_action(core_args)]
                    except ValueError as exc:
                        output_error(str(exc))
                        raise typer.Exit(2) from None
                else:
                    browser_args = _with_local_ai_session(browser_args)
            if operation == "agent":
                browser_args = _with_navigation(browser_args, command, guarded=False)
                browser_args = _with_resolved_local_screenshot_path(browser_args, command)
            try:
                if check is not None and check["session"] != _local_ai_session():
                    launch = browser_policy.isolated_check_launch(str(check["session"]), agent_browser_bin=agent_bin)
                elif managed_session:
                    launch = browser_policy.managed_session_launch(managed_session, agent_browser_bin=agent_bin)
                else:
                    launch = browser_policy.local_launch(browser_args, agent_browser_bin=agent_bin)
            except ValueError as exc:
                output_error(str(exc))
                raise typer.Exit(1) from None
        endpoint = None
    else:
        if operation == "agent":
            browser_args = _with_navigation(browser_args, command, guarded=True)
            browser_args = _with_resolved_local_screenshot_path(browser_args, command)
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
    return request, target == "local-ai" and operation in {"agent", "check"} and not managed_session


def run_registered(record: Any, argv: list[str], context: dict[str, Any]) -> int:
    """Apply core policy, then execute one opaque owner request within the local lock."""
    if not argv or argv[0] in {"--help", "-h"} or argv == ["help"]:
        print(_USAGE)
        return 0
    try:
        selected_tab, parsed_argv = browser_support.selected_tab_options(argv)
    except ValueError as exc:
        output_error(str(exc))
        return 2
    _, browser_args = _parse_browser_target_args(parsed_argv)
    _, browser_args = _parse_engine_args(browser_args)
    command = _agent_command(browser_args)
    focused_help = focused_help_requested(argv)
    if any(arg in {"--help", "-h"} for arg in browser_args) and not focused_help:
        print(_USAGE)
        return 0
    operation = "help" if focused_help else "run" if command == "step" or (selected_tab and command not in {"observe", "run", "extract"}) else command
    if selected_tab:
        declared = getattr(getattr(record, "manifest", None), "structured_operations", {}).get("selected-tabs")
        if declared is None or declared.request_contract_version != 2:
            output_error("Browser owner does not support selected-tab request contract version 2; update the trusted registration and owner")
            return 2
    if operation in _STRUCTURED_OPERATIONS:
        manifest = getattr(record, "manifest", None)
        declarations = getattr(manifest, "structured_operations", {})
        declared = declarations.get(operation)
        if declared is None or declared.request_contract_version != 2:
            output_error(f"Browser owner does not support {operation} request contract version 2; update the trusted browser registration and owner runtime")
            return 2
    request, needs_lock = _build_request(argv, context)
    from ..extensions import dispatch_extension

    launch = cast(dict[str, object], request["launch"])
    managed_session = launch.get("managed_session")
    if managed_session:
        manifest = getattr(record, "manifest", None)
        declared = getattr(manifest, "structured_operations", {}).get("session")
        if declared is None or declared.request_contract_version != 2:
            output_error("Browser owner does not support managed session request contract version 2; update the trusted browser registration and owner runtime")
            return 2
    owner_args = ["--request", json.dumps(request, separators=(",", ":"))]
    if not needs_lock:
        code = dispatch_extension(record, owner_args, context=context)
        if code == 75 and (managed_session or request["operation"] == "session"):
            payload = cast(dict[str, object], request.get("payload", {}))
            selected_name = managed_session or payload.get("name") or "selected"
            output_error(
                f"BROWSER_SESSION_CONFLICT session={selected_name}: inspect its owner and state with `st browser session status {selected_name}`. "
                "If another agent owns it or it is busy, choose a new name with `st browser session create NEW_NAME`, then use `st browser --session NEW_NAME ...`."
            )
        return code
    isolation_root = cast(str | None, launch.get("isolation_root"))
    lock = _local_ai_command_lock(isolation_root=isolation_root) if isolation_root else _local_ai_command_lock()
    with lock as acquired:
        if not acquired:
            output_error("LOCAL_AI_BUSY: this local browser session is active; use `st browser check <url> <png>` for an isolated check or `st browser --proxmox ...`")
            return 75
        return dispatch_extension(record, owner_args, context=context)


_USAGE = """Remote browser automation through st

Default target:
  Interactive commands use local system Chrome profile AI.
  Checks use a fresh isolated headless profile by default.
  Force Proxmox/VM with --proxmox or ST_BROWSER_TARGET=proxmox when VM isolation is better.
  Override VM with ST_BROWSER_HOST, ST_BROWSER_DEFAULT_HOST, or ST_BROWSER_VM_ID.
  Set ST_BROWSER_DISABLE_DEFAULT_VM_HOST=1 to require explicit host config.

Supported workflows:
  st browser capabilities [topic]
  st browser <core-command> --help
  st browser observe [--selector CSS] [--interactive] [--full] [--screenshot PATH]
  st browser run --file actions.json
  st browser step <core-command> [args...]
  st browser extract --file fields.json
  st browser session create NAME | list [--all] | status NAME
  st browser session pause NAME | resume NAME | close NAME
  st browser session view NAME | lease NAME  (paused live view; lease lasts until stdin EOF)
  st browser session maintenance [--idle-ms MS] [--apply]
  st browser selected-tabs list | capabilities | revoke HANDLE
  st browser --selected-tab HANDLE <core-command> [args...]
  st browser --selected-tab HANDLE observe | run --file JSON | extract --file JSON
  st browser --session NAME <core-command> [args...]
  st browser --session NAME workflow run --file DEFINITION --run-id ID [--parameters JSON-file-or-object]
  st browser --session NAME workflow resume RUN_ID [--step ID --resolution completed|retry]
  st browser --session NAME workflow status RUN_ID | cancel RUN_ID
  st browser --session NAME workflow record-start ID
  st browser --session NAME workflow record-stop ID [--file OUTPUT] [--parameters JSON-file-or-object]
  st browser check [--session NAME] <project-or-url> [png] [--viewports desktop,narrow,mobile]
  st browser open <project-or-url>
  st browser screenshot [path] | snapshot | eval <js>
  st browser health | inventory --json | reap-isolated [--dry-run] | update
  st browser url <project>
  st browser --proxmox endpoint [--http|--ws|--json]
  st browser [--chrome|--lp|--engine NAME] <core-command> [args...]

Observe defaults to compact delta output with page text. --interactive selects controls;
--full includes the full observation. Run files contain actions as arrays of strings,
optional postconditions, observation, screenshot and binding. Step runs one action.
Use set-value for native date/time and contenteditable controls;
see st browser set-value --help. Read capabilities controls before unusual inputs.
Structured actions cannot switch sessions, override launch options or close --all.

Managed sessions:
  Set ST_BROWSER_OWNER (or ST_AGENT_ID / CODEX_THREAD_ID) for lifecycle mutations.
  Create a named session before selecting it with --session NAME. Each managed name
  has a persistent private profile and owner-held lock; independent names run concurrently.
  Pause hands the browser to a human; resume restores automation ownership.
  Maintenance previews by default; --apply closes only eligible idle sessions.
  Without --idle-ms, running sessions are never expired for idleness.
  Workflows require an explicit local managed session. Definitions use step action
  arrays; {{name}} scalar parameters are resolved before navigation policy checks.
  Recording retains acknowledged structured actions (run/step), not opaque core commands.
  Selected tabs require an explicit bridge grant handle and stay bound to its origin.
  They accept core actions/observe/run/extract; sessions, checks and workflows are unavailable.

Examples:
  st browser --local-ai open portfolio-ai
  ST_BROWSER_OWNER=agent-a st browser session create research-a
  ST_BROWSER_OWNER=agent-a st browser --session research-a observe --selector main
  st browser step fill @e2 'Two words; literal text'
  st browser run --file /tmp/browser-actions.json
  st browser check a-term /tmp/a-term.png --viewports desktop,mobile
  st browser --proxmox endpoint --ws

Restrictions:
  Do not start arbitrary Chrome, CDP proxies, or agent-browser on the project/server host.
  Local mode uses system Chrome; checks create no desktop window or focus change.
  Named isolated checks can run concurrently; default checks have no shared login state.
  Use check --session st-local-ai for authenticated checks (serialized; closes that session).
  Unqualified interactive commands share the AI profile and remain serialized.
  Explicit alternate local --session names select managed sessions; checks stay isolated.
  ST_BROWSER_LOCAL_AI_VISIBLE=1 / ST_BROWSER_LOCAL_AI_MINIMIZED=1 opt into watched windows.
  Override local Chrome with ST_BROWSER_LOCAL_CHROME, ST_BROWSER_LOCAL_AI_PROFILE.
  With --proxmox, localhost/127.0.0.1 targets are blocked because they point at the browser VM.
  Use st browser url <project>; intentional VM-local targets print a confirmation token.
  Debug override: ST_BROWSER_HOST=127.0.0.1 ST_BROWSER_ALLOW_LOCAL=1 st browser health
  Use st ui when the already-open desktop/PWA is the right evidence source.
"""
_HELP = _USAGE


@app.callback(invoke_without_command=True)
@usage(
    surface="st.browser", cmd="st browser check <url> <png>",
    when="UI render verification; screenshots; DOM snapshots",
    precautions=(
        "local checks use isolated headless sessions; interactive commands share the Chrome AI profile",
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
