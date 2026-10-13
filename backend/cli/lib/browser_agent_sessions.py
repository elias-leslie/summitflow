"""Agent-owned browser sessions: identity, default session, owner hand-off and reaping.

The browser-automation owner keeps session records, locks and launch. This module
only decides which session an agent's plain `st browser` command uses, records
pause reasons and local fallbacks, notifies the owner, and closes sessions nobody
is using (profiles are always kept).
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import browser_support

# The first non-empty value identifies the calling agent. Native session ids come
# before launcher ids so Agent Hub can tell when the agent has ended.
IDENTITY_ENV = ("ST_BROWSER_OWNER", "ST_AGENT_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID",
                "ST_SESSION_ID", "AICO_SESSION_ID")
SHARED_PROFILE_ENV = "ST_BROWSER_SHARED_PROFILE"
LEGACY_SHARED = "shared"
IDLE_CLOSE_MS = 20 * 60_000
PAUSE_CLOSE_MS = 2 * 3600_000
DEAD_OWNER_GRACE_MS = 2 * 60_000
RECLAIM_MIN_IDLE_MS = 60_000
CLAIM_IDLE_MS = IDLE_CLOSE_MS
# The owner's assist window, served by browser-automation and proxied here behind Cloudflare Access.
ASSIST_URL = "https://dev.summitflow.dev/browser-assist"
_ACTOR = re.compile(r"[A-Za-z0-9_.:@/-]+")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def agent_identity(env: Mapping[str, str] | None = None) -> str | None:
    values = os.environ if env is None else env
    for key in IDENTITY_ENV:
        value = values.get(key, "").strip()
        if value and _ACTOR.fullmatch(value):
            return value
    return None


def default_session_name(actor: str, env: Mapping[str, str] | None = None, root: Path | None = None) -> str:
    """Stable, readable per-agent name: project plus a short hash of the agent id."""
    values = os.environ if env is None else env
    project = values.get("AICO_PROJECT_ID", "").strip() or (root or Path.cwd()).name
    label = browser_support.clean_session_component(project)[:24]
    return f"{label}-{hashlib.sha1(actor.encode()).hexdigest()[:8]}"


def profile_actor(profile: str) -> str:
    return f"profile:{profile}"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME", "").strip() or str(Path.home() / ".local" / "state")
    path = Path(base) / "st-browser"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _sessions() -> Any:
    return importlib.import_module("browser_automation.sessions")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _owner_session(action: str, name: str, actor: str) -> tuple[int, dict[str, Any] | None]:
    """Lifecycle mutations go through the registered owner route, as the API does."""
    env = {**os.environ, "ST_BROWSER_OWNER": actor}
    try:
        result = subprocess.run([browser_support.st_bin(), "--no-compact", "browser", "--local-ai", "session", action, name],
                                env=env, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return 1, None
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        value = None
    return result.returncode, value if isinstance(value, dict) else None


def session_state(name: str, actor: str, *, field: str = "state") -> str:
    """missing | active | paused | closed | busy | foreign (owned by another actor).

    field="runtime_state" reads running | dormant | unknown for an existing session instead.
    """
    sessions = _sessions()
    previous = os.environ.get("ST_BROWSER_OWNER")
    os.environ["ST_BROWSER_OWNER"] = actor
    try:
        return str(sessions.status(name, actor)[field])
    except sessions.SessionBusy:
        return "busy"
    except sessions.SessionError as exc:
        if "another actor" in str(exc):
            return "foreign"
        return "missing" if not (sessions.state_base() / sessions._key(name) / "session.json").exists() else "invalid"
    finally:
        if previous is None:
            os.environ.pop("ST_BROWSER_OWNER", None)
        else:
            os.environ["ST_BROWSER_OWNER"] = previous


def ensure_session(name: str, actor: str) -> str | None:
    """Make NAME usable for ACTOR; return an error message instead of switching sessions."""
    state = session_state(name, actor)
    if state == "busy" or state == "active":
        return None  # A concurrent command holds it; the owner lock serializes the rest.
    if state == "missing":
        code, _ = _owner_session("create", name, actor)
        if code == 0:
            if actor.startswith(profile_actor("")):
                print(f"[st] Shared browser session {name} registered (one agent at a time; "
                      f"`st browser session release {name}` when done).", file=sys.stderr)
            else:
                print(f"[st] Browser session {name} created for this agent on the browser VM "
                      f"(own profile; close it with `st browser session close` when done).", file=sys.stderr)
            return None
        return f"BROWSER_SESSION_CREATE_FAILED session={name}: inspect `st browser session status {name}`"
    if state == "closed":
        code, _ = _owner_session("resume", name, actor)
        return None if code == 0 else f"BROWSER_SESSION_REOPEN_FAILED session={name}"
    if state == "paused":
        reason = pause_reason(name)
        return (f"BROWSER_SESSION_PAUSED session={name}: the owner has this browser"
                f"{f' ({reason})' if reason else ''}. Wait with `st browser session wait {name}`, then retry.")
    if state == "foreign":
        return f"BROWSER_SESSION_CONFLICT session={name} belongs to another agent; use your own session or --session NEW_NAME"
    return f"BROWSER_SESSION_INVALID session={name}: inspect `st browser session status {name}`"


def warm_session(name: str, actor: str) -> bool:
    """Start NAME's daemon (a read-only page query) so a paused session has a live view to attach to."""
    if session_state(name, actor) != "active" or session_state(name, actor, field="runtime_state") == "running":
        return True
    env = {**os.environ, "ST_BROWSER_OWNER": actor}
    env.pop(SHARED_PROFILE_ENV, None)
    try:
        result = subprocess.run([browser_support.st_bin(), "--no-compact", "browser", "--session", name, "get", "url"],
                                env=env, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


# Shared profiles: one holder at a time, held across commands until released,
# idle for CLAIM_IDLE_MS, or the holder ends.

def _claim_path(profile: str) -> Path:
    return state_dir() / "claims" / f"{browser_support.clean_session_component(profile)}.json"


@contextmanager
def _claims_lock() -> Iterator[None]:
    path = state_dir() / "claims.lock"
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def claim_profile(profile: str, holder: str, *, owner_alive: Callable[[str], bool | None] | None = None) -> str | None:
    """Take or refresh PROFILE for HOLDER; return a conflict message if another live agent holds it."""
    alive = owner_alive or agent_alive
    with _claims_lock():
        path = _claim_path(profile)
        claim = _read_json(path)
        now = _now_ms()
        if claim and claim.get("holder") != holder:
            idle = now - int(claim.get("used_ms", 0))
            if idle < CLAIM_IDLE_MS and alive(str(claim.get("holder"))) is not False:
                return (f"SHARED_PROFILE_HELD profile={profile} holder={claim.get('holder')} idle={idle // 60_000}m: "
                        "another agent is using this profile. Wait for it to finish (claims lapse after "
                        f"{CLAIM_IDLE_MS // 60_000} min idle) or use your own session.")
        since = claim.get("since_ms", now) if claim and claim.get("holder") == holder else now
        _write_json(path, {"profile": profile, "holder": holder, "since_ms": since, "used_ms": now})
    return None


def release_profile(profile: str, holder: str) -> bool:
    with _claims_lock():
        path = _claim_path(profile)
        claim = _read_json(path)
        if not claim or claim.get("holder") != holder:
            return False
        path.unlink(missing_ok=True)
    return True


def claims() -> list[dict[str, Any]]:
    folder = state_dir() / "claims"
    return [claim for path in sorted(folder.glob("*.json")) if (claim := _read_json(path))] if folder.is_dir() else []


# Owner hand-off: pause reasons, Nightshift push and waiting for resume.

def _pause_path(name: str) -> Path:
    return state_dir() / "pauses" / f"{browser_support.clean_session_component(name)}.json"


def pause_reason(name: str) -> str | None:
    record = _read_json(_pause_path(name))
    reason = record.get("reason") if record else None
    return reason if isinstance(reason, str) and reason else None


def pause_record(name: str) -> dict[str, Any] | None:
    return _read_json(_pause_path(name))


def record_pause(name: str, actor: str, reason: str | None) -> None:
    _write_json(_pause_path(name), {"name": name, "actor": actor, "reason": reason or "", "since_ms": _now_ms()})


def clear_pause(name: str) -> None:
    _pause_path(name).unlink(missing_ok=True)


def assist_link(name: str) -> str:
    return f"{ASSIST_URL}/{quote(name, safe='')}"


def _assist() -> Any:
    return importlib.import_module("browser_automation.assist")


def notify_owner(name: str, reason: str) -> bool:
    """One Nightshift Web Push linking to the session's assist window."""
    message = f"{reason} (browser session {name}). Open it, finish, then press Done."
    try:
        result = subprocess.run(["nightshift", "push", "--title", "Browser needs you", "--severity", "warning",
                                 "--open", assist_link(name), message[:300]],
                                capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def hand_off(name: str, actor: str, reason: str, question: str = "") -> str:
    """window (owner at the workstation), push, repeat (already handed off) or failed."""
    try:
        started = _assist().ensure(name, actor, reason=reason, question=question, st_bin=browser_support.st_bin())
    except (ValueError, OSError):
        started = {"started": False, "window": False, "error": True}
    if not started["started"] and not started.get("error"):
        return "repeat"
    if started["window"]:
        return "window"
    return "push" if notify_owner(name, reason) else "failed"


def wait_result(name: str, code: int) -> tuple[int, dict[str, Any]]:
    """Exit code and JSON for a finished wait; a declined --ask question exits 4."""
    outcome = {0: "resumed", 3: "closed", 124: "timeout"}[code]
    answer = _assist().take_answer(name) if code == 0 else None
    if answer == "approve":
        outcome = "approved"
    elif answer == "decline":
        outcome, code = "declined", 4
    return code, {"schema_version": 1, "name": name, "resumed": code in {0, 4}, "outcome": outcome}


def wait_for_resume(name: str, actor: str, timeout_s: int, *, poll_s: float = 3.0,
                    state: Callable[[str, str], str] | None = None) -> int:
    """0 resumed, 3 closed or gone, 124 still paused at the timeout."""
    read = state or session_state
    deadline = time.monotonic() + timeout_s
    while True:
        current = read(name, actor)
        if current == "active":
            return 0
        if current not in {"paused", "busy"}:
            return 3
        if time.monotonic() >= deadline:
            return 124
        time.sleep(poll_s)


# Local fallbacks are recorded for Nightshift (ws.browser.local_fallbacks).

def record_local_fallback(command: str | None, reason: str) -> None:
    try:
        with (state_dir() / "local-fallbacks.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at_ms": _now_ms(), "actor": agent_identity() or "", "command": command or "",
                                     "reason": reason}) + "\n")
    except OSError:
        pass


# Reaping: close sessions nobody uses, on the existing agent-browser reaper timer.

def agent_alive(actor: str) -> bool | None:
    """False only when Agent Hub knows the agent session and it is no longer active."""
    if not _UUID.fullmatch(actor):
        return None
    try:
        from ..client import STClient

        session = STClient(require_project=False).get_session(actor)
    except Exception:  # Unknown is not dead.
        return None
    status = session.get("status") if isinstance(session, dict) else None
    return None if not isinstance(status, str) else status == "active"


def reap_decision(session: dict[str, Any], now_ms: int, *, alive: Callable[[str], bool | None],
                  paused_since: Callable[[str], int | None]) -> str | None:
    """Why a running session should close now, or None to keep it."""
    if session.get("runtime_state") != "running":
        return None
    name, actor, last_used = str(session["name"]), str(session["actor"]), int(session.get("last_used_ms") or 0)
    if session.get("paused"):
        since = paused_since(name) or last_used
        return "paused too long" if now_ms - since >= PAUSE_CLOSE_MS else None
    idle = now_ms - last_used
    if idle >= IDLE_CLOSE_MS:
        return "idle"
    if idle >= DEAD_OWNER_GRACE_MS and alive(actor) is False:
        return "owner ended"
    return None


def _paused_since(name: str) -> int | None:
    record = pause_record(name)
    since = record.get("since_ms") if record else None
    return since if isinstance(since, int) else None


def close_session(name: str, actor: str) -> bool:
    code, value = _owner_session("close", name, actor)
    if code == 0:
        clear_pause(name)
    return code == 0 and bool(value and value.get("closed", True))


def reap(*, dry_run: bool = False, now_ms: int | None = None,
         inventory: Callable[[], list[dict[str, Any]]] | None = None,
         alive: Callable[[str], bool | None] | None = None,
         close: Callable[[str, str], bool] | None = None,
         vm_orphans: Callable[[set[str]], list[str]] | None = None) -> dict[str, Any]:
    now = now_ms or _now_ms()
    sessions = (inventory or _sessions().operator_inventory)()
    cache: dict[str, bool | None] = {}

    def alive_cached(actor: str) -> bool | None:
        if actor not in cache:
            cache[actor] = (alive or agent_alive)(actor)
        return cache[actor]

    closed, kept = [], 0
    for session in sessions:
        reason = reap_decision(session, now, alive=alive_cached, paused_since=_paused_since)
        if reason is None:
            kept += session.get("runtime_state") == "running"
            continue
        ok = True if dry_run else (close or close_session)(str(session["name"]), str(session["actor"]))
        closed.append({"name": session["name"], "reason": reason, "closed": ok})
    released = []
    for claim in claims():
        holder, used = str(claim.get("holder")), int(claim.get("used_ms", 0))
        if now - used >= CLAIM_IDLE_MS or alive_cached(holder) is False:
            if not dry_run:
                release_profile(str(claim.get("profile")), holder)
            released.append(claim.get("profile"))
    gone = {item["name"] for item in closed if item["closed"]}
    running = {browser_support.vm_session_key(str(item["name"])) for item in sessions
               if item.get("runtime_state") == "running" and item["name"] not in gone}
    stopped = [] if dry_run or vm_orphans is None else vm_orphans(running)
    return {"dry_run": dry_run, "closed": closed, "running_kept": kept, "claims_released": released,
            "vm_orphans_stopped": stopped}


def reclaim_one(exclude: str, *, now_ms: int | None = None,
                inventory: Callable[[], list[dict[str, Any]]] | None = None,
                close: Callable[[str, str], bool] | None = None) -> str | None:
    """At VM capacity: close the least recently used idle VM session (never paused ones)."""
    now = now_ms or _now_ms()
    candidates = sorted(
        (item for item in (inventory or _sessions().operator_inventory)()
         if item.get("runtime_state") == "running" and not item.get("paused") and item.get("name") not in {exclude, LEGACY_SHARED}
         and (item.get("runtime") or {}).get("target") == "proxmox"
         and now - int(item.get("last_used_ms") or 0) >= RECLAIM_MIN_IDLE_MS),
        key=lambda item: int(item.get("last_used_ms") or 0))
    for item in candidates:
        if (close or close_session)(str(item["name"]), str(item["actor"])):
            return str(item["name"])
    return None
