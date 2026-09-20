"""SummitFlow-owned browser routing and local-workstation policy."""

from __future__ import annotations

import fcntl
import os
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from hashlib import sha1
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from app.services.browser_routes import BrowserRouteError, resolve_browser_location

from . import browser_support

HELP_ARGS = {"-h", "--help", "help"}
NAVIGATION_COMMANDS = {"open", "goto", "navigate"}
LOCAL_AI_FLAG = "--local-ai"
LOCAL_AI_COMMAND = "local-ai"
PROXMOX_FLAG = "--proxmox"
PROXMOX_COMMAND = "proxmox"
LOCAL_URL_CONFIRM_ENV = "ST_BROWSER_CONFIRM_LOCAL_URL"
DEFAULT_LOCAL_AI_SESSION = "st-local-ai"
DEFAULT_LOCAL_AI_PROFILE = "AI"
LOCAL_AI_WINDOW_CLASS = "st-browser-ai"
LOCAL_CHROME_CANDIDATES = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
MINIMIZED_CHROME_ARGS = (
    f"--class={LOCAL_AI_WINDOW_CLASS},--start-minimized,--disable-renderer-backgrounding,"
    "--disable-backgrounding-occluded-windows,--disable-background-timer-throttling,"
    "--disable-features=CalculateNativeWinOcclusion"
)
HEADLESS_CHROME_ARGS = (
    "--enable-gpu,--use-angle=vulkan,--enable-features=Vulkan,"
    "--disable-vulkan-surface,--disable-software-rasterizer"
)


def parse_target_args(args: list[str], env: Mapping[str, str] | None = None) -> tuple[str, list[str]]:
    values = os.environ if env is None else env
    target = values.get("ST_BROWSER_TARGET", "").strip().lower() or "local-ai"
    if values.get("ST_BROWSER_LOCAL_AI", "").strip() == "1":
        target = "local-ai"
    if values.get("ST_BROWSER_FORCE_PROXMOX", "").strip() == "1":
        target = "proxmox"
    remaining: list[str] = []
    for index, arg in enumerate(args):
        if arg == LOCAL_AI_FLAG or (index == 0 and arg == LOCAL_AI_COMMAND):
            target = "local-ai"
        elif arg == PROXMOX_FLAG or (index == 0 and arg == PROXMOX_COMMAND):
            target = "proxmox"
        else:
            remaining.append(arg)
    if target in {"vm", "browser-vm", "remote"}:
        target = "proxmox"
    if target not in {"local-ai", "proxmox"}:
        target = "local-ai"
    return target, remaining


def url_hostname(value: str) -> str | None:
    try:
        hostname = urlsplit(value.strip()).hostname
    except ValueError:
        return None
    return hostname.lower().rstrip(".") if hostname else None


def is_local_browser_url(value: str) -> bool:
    hostname = url_hostname(value)
    if not hostname:
        return False
    if hostname == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def local_url_display_host(value: str) -> str:
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


def local_url_confirmation_token(value: str) -> str:
    host = local_url_display_host(value)
    return sha1(f"st-browser-local-url:{host}".encode()).hexdigest()[:8]


def local_browser_url_error(value: str, env: Mapping[str, str] | None = None) -> str | None:
    if not is_local_browser_url(value):
        return None
    values = os.environ if env is None else env
    token = local_url_confirmation_token(value)
    if values.get(LOCAL_URL_CONFIRM_ENV, "").strip() == token:
        return None
    host = local_url_display_host(value)
    return (
        f"PROXMOX_LOCAL_URL_BLOCKED target={host}: localhost/loopback points at the browser VM, not this project. "
        "Use `st browser url <project>` for its VM-reachable URL. If this VM-local target is intentional, "
        f"retry with {LOCAL_URL_CONFIRM_ENV}={token}."
    )


def resolve_guarded_location(value: str, env: Mapping[str, str] | None = None) -> str:
    resolved = resolve_browser_location(value)
    if message := local_browser_url_error(resolved, env):
        raise BrowserRouteError(message)
    return resolved


def command_index(args: list[str]) -> int | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return index
        index += 2 if arg in browser_support.AGENT_BROWSER_OPTIONS_WITH_VALUE else 1
    return None


def has_agent_option(args: list[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def system_chrome_path(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    configured = values.get("ST_BROWSER_LOCAL_CHROME", "").strip()
    if configured:
        return configured
    for candidate in LOCAL_CHROME_CANDIDATES:
        if path := shutil.which(candidate):
            return path
    return ""


def local_ai_window_mode(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    if values.get("ST_BROWSER_LOCAL_AI_VISIBLE", "").strip() == "1":
        return "visible"
    if values.get("ST_BROWSER_LOCAL_AI_MINIMIZED", "").strip() == "1":
        return "minimized"
    return "headless"


def local_ai_session(env: Mapping[str, str] | None = None) -> str:
    values = os.environ if env is None else env
    return browser_support.clean_session_component(
        values.get("ST_BROWSER_LOCAL_AI_SESSION", "").strip() or DEFAULT_LOCAL_AI_SESSION
    )


def with_local_ai_session(args: list[str], env: Mapping[str, str] | None = None) -> list[str]:
    requested = browser_support.session_args(args)
    expected = local_ai_session(env)
    if requested and requested[1] != expected:
        raise ValueError(
            f"LOCAL_AI_SESSION_BLOCKED requested={requested[1]} allowed={expected}: "
            "the operator workstation permits one local AI Chrome session; "
            f"use `st browser --proxmox --session {requested[1]} ...` for isolated or parallel browser work"
        )
    return args if requested else ["--session", expected, *args]


def local_ai_lock_path(env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    runtime_root = Path(values.get("XDG_RUNTIME_DIR", "").strip() or f"/tmp/st-browser-{os.getuid()}")
    return runtime_root / "st-browser-local-ai" / "command.lock"


@contextmanager
def local_ai_command_lock(env: Mapping[str, str] | None = None) -> Iterator[bool]:
    lock_path = local_ai_lock_path(env)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def local_agent_prefix(args: list[str], env: Mapping[str, str] | None = None) -> list[str]:
    """Prepare local Chrome options without resolving or launching its executor."""
    values = os.environ if env is None else env
    prefix: list[str] = []
    if not has_agent_option(args, "--profile") and not values.get("AGENT_BROWSER_PROFILE", "").strip():
        prefix.extend(["--profile", values.get("ST_BROWSER_LOCAL_AI_PROFILE", "").strip() or DEFAULT_LOCAL_AI_PROFILE])
    if not has_agent_option(args, "--executable-path") and not values.get("AGENT_BROWSER_EXECUTABLE_PATH", "").strip():
        chrome = system_chrome_path(values)
        if not chrome:
            raise ValueError(
                "Local system Chrome not found; set ST_BROWSER_LOCAL_CHROME or use `st browser --proxmox`"
            )
        prefix.extend(["--executable-path", chrome])
    mode = local_ai_window_mode(values)
    if mode != "headless" and not has_agent_option(args, "--headed") and not values.get("AGENT_BROWSER_HEADED", "").strip():
        prefix.append("--headed")
    if not has_agent_option(args, "--args") and not values.get("AGENT_BROWSER_ARGS", "").strip():
        prefix.extend(["--args", MINIMIZED_CHROME_ARGS if mode == "minimized" else HEADLESS_CHROME_ARGS]) if mode != "visible" else None
    return prefix


def local_launch(args: list[str], *, agent_browser_bin: str, env: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if env is None else env
    prefix = local_agent_prefix(args, values)
    mode = local_ai_window_mode(values)
    launch_options = ("--profile", "--executable-path", "--args", "--headed")
    launch_envs = (
        "AGENT_BROWSER_PROFILE", "AGENT_BROWSER_EXECUTABLE_PATH", "AGENT_BROWSER_ARGS", "AGENT_BROWSER_HEADED",
        "ST_BROWSER_LOCAL_AI_MINIMIZED", "ST_BROWSER_LOCAL_AI_PROFILE", "ST_BROWSER_LOCAL_CHROME",
    )
    default_launch = mode != "visible" and not any(has_agent_option(args, option) for option in launch_options) and not any(
        values.get(name, "").strip() for name in launch_envs
    )
    return {
        "agent_browser_bin": agent_browser_bin,
        "prefix": prefix,
        "window_mode": mode,
        "default_launch": default_launch,
        "minimize": mode == "minimized",
        "window_class": LOCAL_AI_WINDOW_CLASS,
    }


def absolute_output_path(path: str, cwd: Path | None = None) -> str:
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = (cwd or Path.cwd()) / target
    target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)
