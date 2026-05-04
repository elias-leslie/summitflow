"""Responsive browser check implementation for `st browser check`."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .browser_support import (
    browser_page_target_ids,
    close_browser_targets,
    json_from_agent_eval,
    suffixed,
)

RunAgent = Callable[..., subprocess.CompletedProcess[str]]


def _agent_failure(
    label: str,
    result: subprocess.CompletedProcess[str],
    summary_hint: Callable[[str], str],
) -> str | None:
    if result.returncode == 0:
        return None
    output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    return f"{label}: rc={result.returncode} hint={summary_hint(output) if output else '-'}"


def _check_viewports(screenshot_path: str, env: Mapping[str, str]) -> list[tuple[str, int, int, str]]:
    viewports = [
        (
            "desktop",
            int(env.get("ST_BROWSER_CHECK_DESKTOP_WIDTH", "1600")),
            int(env.get("ST_BROWSER_CHECK_DESKTOP_HEIGHT", "900")),
            screenshot_path,
        ),
        (
            "narrow",
            int(env.get("ST_BROWSER_CHECK_NARROW_WIDTH", "1180")),
            int(env.get("ST_BROWSER_CHECK_NARROW_HEIGHT", "900")),
            suffixed(screenshot_path, "-narrow"),
        ),
        (
            "mobile",
            int(env.get("ST_BROWSER_CHECK_MOBILE_WIDTH", "390")),
            int(env.get("ST_BROWSER_CHECK_MOBILE_HEIGHT", "844")),
            suffixed(screenshot_path, "-mobile"),
        ),
    ]
    return viewports[:1] if env.get("ST_BROWSER_CHECK_RESPONSIVE") == "0" else viewports


def _append_collected_details(
    detail_lines: list[str],
    *,
    errors: dict[str, object] | list[object],
    network: dict[str, object] | list[object],
    command_warnings: list[str],
) -> tuple[list[object], list[object], list[object]]:
    raw_errors = errors.get("errors", []) if isinstance(errors, dict) else []
    raw_warnings = errors.get("warnings", []) if isinstance(errors, dict) else []
    error_items: list[object] = [item for item in raw_errors] if isinstance(raw_errors, list) else []
    warning_items: list[object] = [item for item in raw_warnings] if isinstance(raw_warnings, list) else []
    network_items: list[object] = list(network) if isinstance(network, list) else []
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
    return error_items, warning_items, network_items


def run_browser_check(
    args: list[str],
    *,
    output_error: Callable[[str], None],
    resolve_browser_location: Callable[[str], str],
    select_port: Callable[[str | None], int],
    host_for_engine: Callable[[str | None], str],
    cdp_ws: Callable[..., str | None],
    run_agent: RunAgent,
    run_browser_reaper: Callable[[], None],
    current_root: Callable[[], Path],
    write_details: Callable[[Path, str, str], Path],
    display_path: Callable[[Path, Path], str],
    summary_hint: Callable[[str], str],
    browser_route_error: type[Exception],
    env: Mapping[str, str] | None = None,
) -> int:
    env_values = os.environ if env is None else env
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
    try:
        url = resolve_browser_location(args[0])
    except browser_route_error as exc:
        output_error(str(exc))
        return 2
    screenshot_path = args[1] if len(args) > 1 else "/tmp/st-browser-check.png"
    session_args = ["--session", session or f"st-browser-check-{os.getpid()}-{time.time_ns()}"]
    port = select_port("chrome")
    host = host_for_engine("chrome")
    ws = cdp_ws(port, host=host)
    if not ws:
        output_error(f"Unable to resolve Chrome CDP endpoint on {host}:{port}")
        return 1
    baseline_targets = browser_page_target_ids(host, port)

    command_warnings: list[str] = []
    error_result = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
    network_result = subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
    viewports = _check_viewports(screenshot_path, env_values)
    try:
        first_viewport = run_agent(
            [*session_args, "set", "viewport", str(viewports[0][1]), str(viewports[0][2])],
            cdp=ws,
            capture=True,
        )
        if warning := _agent_failure("initial viewport", first_viewport, summary_hint):
            command_warnings.append(warning)
        open_result = run_agent([*session_args, "open", url], cdp=ws, capture=True)
        if open_result.returncode != 0:
            if warning := _agent_failure("open", open_result, summary_hint):
                output_error(warning)
            return open_result.returncode
        load_wait = run_agent([*session_args, "wait", env_values.get("ST_BROWSER_CHECK_WAIT", "5000")], cdp=ws, capture=True)
        if warning := _agent_failure("load wait", load_wait, summary_hint):
            command_warnings.append(warning)
        hook_result = run_agent(
            [
                *session_args,
                "eval",
                "window.__sfErrors=[];window.__sfWarnings=[];"
                "const oe=console.error;console.error=(...a)=>{window.__sfErrors.push(a.map(String).join(' '));oe.apply(console,a)};"
                "const ow=console.warn;console.warn=(...a)=>{window.__sfWarnings.push(a.map(String).join(' '));ow.apply(console,a)};'capturing'",
            ],
            cdp=ws,
            capture=True,
        )
        if warning := _agent_failure("console hook", hook_result, summary_hint):
            command_warnings.append(warning)
        settle = run_agent([*session_args, "wait", "2000"], cdp=ws, capture=True)
        if warning := _agent_failure("settle wait", settle, summary_hint):
            command_warnings.append(warning)

        for label, width, height, path in viewports:
            viewport = run_agent([*session_args, "set", "viewport", str(width), str(height)], cdp=ws, capture=True)
            if warning := _agent_failure(f"{label} viewport", viewport, summary_hint):
                command_warnings.append(warning)
            viewport_wait = run_agent(
                [*session_args, "wait", env_values.get("ST_BROWSER_CHECK_VIEWPORT_SETTLE_MS", "350")],
                cdp=ws,
                capture=True,
            )
            if warning := _agent_failure(f"{label} wait", viewport_wait, summary_hint):
                command_warnings.append(warning)
            screenshot = run_agent([*session_args, "screenshot", path], cdp=ws, capture=True)
            if warning := _agent_failure(f"{label} screenshot", screenshot, summary_hint):
                command_warnings.append(warning)

        error_result = run_agent(
            [
                *session_args,
                "eval",
                "JSON.stringify({errors:window.__sfErrors||[],warnings:window.__sfWarnings||[],url:location.href,title:document.title})",
            ],
            cdp=ws,
            capture=True,
        )
        if warning := _agent_failure("console read", error_result, summary_hint):
            command_warnings.append(warning)
        network_result = run_agent(
            [
                *session_args,
                "eval",
                "JSON.stringify(performance.getEntriesByType('resource').filter(e=>e.responseStatus>=400).map(e=>e.responseStatus+' '+e.name.split('/').pop()))",
            ],
            cdp=ws,
            capture=True,
        )
        if warning := _agent_failure("network read", network_result, summary_hint):
            command_warnings.append(warning)
    finally:
        close_result = run_agent([*session_args, "close"], cdp=ws, capture=True)
        if warning := _agent_failure("close", close_result, summary_hint):
            command_warnings.append(warning)
        run_browser_reaper()
        remaining_targets = browser_page_target_ids(host, port)
        if baseline_targets is not None and remaining_targets is not None:
            close_browser_targets(host, port, remaining_targets - baseline_targets)

    detail_lines = [
        f"Screenshot: {screenshot_path}",
        "Responsive set: " + ", ".join(f"{label} {width}x{height}" for label, width, height, _ in viewports),
    ]
    if len(viewports) > 1:
        detail_lines.append("Additional screenshots:")
        for label, _, _, path in viewports[1:]:
            detail_lines.append(f"  {label}: {path}")
    errors = json_from_agent_eval(error_result.stdout)
    network = json_from_agent_eval(network_result.stdout)
    error_items, warning_items, network_items = _append_collected_details(
        detail_lines,
        errors=errors,
        network=network,
        command_warnings=command_warnings,
    )
    root = current_root()
    details = write_details(root, "browser-check", "\n".join(detail_lines))
    status = "OK" if not error_items and not warning_items and not network_items else "ISSUES"
    print(
        f"BROWSER_CHECK:{status}|errors={len(error_items)}|warnings={len(warning_items)}|"
        f"network={len(network_items)}|command_warnings={len(command_warnings)}|"
        f"screenshot={screenshot_path}|details:{display_path(root, details)}"
    )
    return 0
