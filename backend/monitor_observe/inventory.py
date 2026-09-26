"""Fixed-source, read-only host and software inventories."""
from __future__ import annotations

import hashlib
import os
import platform
import re
import stat
from pathlib import Path
from typing import Any

from .common import ObserveQueryError, availability, base, bounded_text, error, item, limits, pack
from .logs import _run

OS_RELEASE = Path("/etc/os-release")
PASSWD = Path("/etc/passwd")
MODULES = Path("/proc/modules")
MAX_SOURCE_BYTES = 512 * 1024
MAX_SESSION_ROWS = 100
MAX_AUTOSTART_FILES = 256
MAX_DESKTOP_BYTES = 4096
AUTOSTART_DIRS = (Path("/etc/xdg/autostart"), Path.home() / ".config/autostart")


def _lines(path: Path) -> list[str]:
    with path.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("source exceeds read cap")
    return raw.decode("utf-8", "replace").splitlines()


def _failure(payload: dict[str, Any], source: str, exc: BaseException, *,
             limit: int, max_bytes: int) -> dict[str, Any]:
    code = availability(exc)
    payload["coverage"] = {"availability": code}
    payload["errors"].append(error(code, source))
    return pack(payload, [], limit=limit, max_bytes=max_bytes)


def query_system_info(*, max_bytes: int = 4096) -> dict[str, Any]:
    """Static OS and hardware identity without serial numbers or unique IDs."""
    limits(1, max_bytes)
    payload = base("system_info")
    release: dict[str, str] = {}
    release_status = "ok"
    try:
        for line in _lines(OS_RELEASE):
            if "=" in line:
                key, value = line.split("=", 1)
                if key in {"NAME", "VERSION_ID", "PRETTY_NAME", "ID"}:
                    release[key.lower()] = bounded_text(value.strip('"'), 128)
    except (OSError, ValueError) as exc:
        release_status = availability(exc)
        payload["errors"].append(error(availability(exc), str(OS_RELEASE)))
    uname = platform.uname()
    data = {"system": uname.system, "release": uname.release, "machine": uname.machine,
            "processor": bounded_text(uname.processor, 128), "logical_cpus": os.cpu_count(),
            "os_release": release}
    payload["coverage"] = {"availability": "ok", "providers": {"uname": "ok",
                            "os_release": release_status}}
    return pack(payload, [item("uname", "python-platform", "ok", data)], limit=1,
                max_bytes=max_bytes)


def _active_sessions() -> tuple[list[dict[str, Any]], str, bool]:
    """Read a capped local loginctl table; emit no session ID, tty or remote field."""
    argv = ["loginctl", "list-sessions", "--no-legend", "--no-pager", "--no-ask-password"]
    try:
        stdout, stderr, returncode, clipped = _run(argv)
    except (OSError, TimeoutError) as exc:
        return [], availability(exc), False
    if returncode:
        text = stderr[:512].decode("utf-8", "replace").lower()
        code = "permission_denied" if "permission denied" in text or "access denied" in text else "unsupported" if "not been booted with systemd" in text or "failed to connect to bus" in text else "error"
        return [], code, False
    rows = stdout.decode("utf-8", "replace").splitlines()
    capped = clipped or len(rows) > MAX_SESSION_ROWS
    if clipped and rows:
        rows = rows[:-1]
    entries: list[dict[str, Any]] = []
    malformed = False
    for line in rows[:MAX_SESSION_ROWS]:
        parts = line.split()
        if len(parts) < 6 or not parts[0].isascii() or not parts[0].isalnum():
            malformed = True
            continue
        try:
            uid = int(parts[1])
        except ValueError:
            malformed = True
            continue
        if uid < 0 or parts[5] not in {"active", "online", "closing"}:
            malformed = True
            continue
        if parts[5] == "active":
            entries.append(item("loginctl", "systemd-logind", "ok",
                                {"kind": "active_session", "uid": uid, "state": "active"}))
    return entries, "partial" if capped or malformed else "ok", capped


def query_users(*, limit: int = 10, max_bytes: int = 4096) -> dict[str, Any]:
    """Local account inventory and bounded active sessions from loginctl."""
    limits(limit, max_bytes)
    payload = base("users")
    accounts: list[dict[str, Any]] = []
    account_status = "ok"
    try:
        for line in _lines(PASSWD):
            fields = line.split(":")
            if len(fields) < 7:
                continue
            try:
                uid = int(fields[2])
            except ValueError:
                continue
            accounts.append(item(str(PASSWD), "passwd", "ok",
                                 {"kind": "account", "name": bounded_text(fields[0], 64),
                                  "uid": uid, "shell": bounded_text(fields[6], 128)}))
    except (OSError, ValueError) as exc:
        account_status = availability(exc)
        payload["errors"].append(error(account_status, str(PASSWD)))
    sessions, session_status, session_capped = _active_sessions()
    if session_status != "ok":
        payload["errors"].append(error("source_truncated" if session_capped else session_status, "loginctl"))
    payload["coverage"] = {
        "availability": "ok" if account_status == session_status == "ok" else "partial" if accounts or sessions else account_status if account_status != "ok" else session_status,
        "accounts": account_status, "accounts_seen": len(accounts),
        "sessions": session_status, "active_sessions_seen": len(sessions),
        "sessions_capped": session_capped,
    }
    return pack(payload, sessions + accounts, limit=limit, max_bytes=max_bytes,
                more=session_capped)

def _desktop_metadata(path: Path) -> dict[str, Any] | None:
    """Read only selected Desktop Entry keys from a regular, non-symlink file."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        raw = os.read(descriptor, MAX_DESKTOP_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_DESKTOP_BYTES:
        raise ValueError("desktop entry exceeds cap")
    inside = False
    values: dict[str, str] = {}
    for line in raw.decode("utf-8", "replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            inside = stripped == "[Desktop Entry]"
        elif inside and "=" in line:
            key, value = line.split("=", 1)
            if key in {"Name", "Hidden", "OnlyShowIn"}:
                values[key] = bounded_text(value.strip(), 128)
    if "Name" not in values:
        return None
    return {"kind": "desktop_autostart", "name": values["Name"],
            "hidden": values.get("Hidden", "false").lower() == "true",
            "only_show_in": values.get("OnlyShowIn")}


def query_startup(*, limit: int = 10, max_bytes: int = 4096) -> dict[str, Any]:
    """Enabled user services and fixed-directory desktop autostart metadata."""
    limits(limit, max_bytes)
    payload = base("startup")
    entries: list[dict[str, Any]] = []
    providers: dict[str, str] = {}
    try:
        stdout, _stderr, returncode, clipped = _run(
            ["systemctl", "--user", "list-unit-files", "--type=service",
             "--state=enabled", "--no-legend", "--plain", "--no-pager"])
        if returncode and not clipped:
            providers["systemd_user"] = "error"
            payload["errors"].append(error("error", "systemctl"))
        else:
            lines = stdout.decode("utf-8", "replace").splitlines()
            providers["systemd_user"] = "partial" if clipped or len(lines) > MAX_AUTOSTART_FILES else "ok"
            if clipped or len(lines) > MAX_AUTOSTART_FILES:
                payload["errors"].append(error("source_truncated", "systemctl"))
            for line in lines[:MAX_AUTOSTART_FILES]:
                parts = line.split()
                if parts and parts[0].endswith(".service"):
                    entries.append(item("systemctl", "systemd", "ok",
                                        {"kind": "systemd_user_unit", "unit": bounded_text(parts[0], 128),
                                         "state": bounded_text(parts[1], 32) if len(parts) > 1 else None}))
    except (OSError, TimeoutError) as exc:
        providers["systemd_user"] = availability(exc)
        payload["errors"].append(error(availability(exc), "systemctl"))

    desktop_entries: list[dict[str, Any]] = []
    seen = 0
    scanned = 0
    denied = 0
    failures = 0
    capped = False
    available_dirs = 0
    for directory_index, directory in enumerate(AUTOSTART_DIRS):
        try:
            with os.scandir(directory) as stream:
                available_dirs += 1
                for entry in stream:
                    if not entry.name.endswith(".desktop") or not entry.is_file(follow_symlinks=False):
                        continue
                    seen += 1
                    if scanned >= MAX_AUTOSTART_FILES:
                        capped = True
                        break
                    scanned += 1
                    try:
                        metadata = _desktop_metadata(Path(entry.path))
                        if metadata:
                            desktop_entries.append(item("system_autostart" if directory_index == 0 else "user_autostart", "desktop-entry", "ok", metadata))
                    except (OSError, ValueError) as exc:
                        failures += 1
                        if isinstance(exc, PermissionError):
                            denied += 1
                        payload["errors"].append(error(availability(exc), "desktop_autostart"))
        except FileNotFoundError:
            continue
        except OSError as exc:
            failures += 1
            payload["errors"].append(error(availability(exc), "desktop_autostart"))
            if isinstance(exc, PermissionError):
                denied += 1
    providers["desktop_autostart"] = "partial" if capped or failures else "ok" if available_dirs else "unsupported"
    if capped:
        payload["errors"].append(error("source_truncated", "desktop_autostart"))
    payload["coverage"] = {
        "availability": "ok" if all(status == "ok" for status in providers.values()) else "partial" if entries or desktop_entries else "unsupported",
        "providers": providers, "desktop_files_seen": seen,
        "desktop_files_scanned": scanned, "desktop_permission_denied": denied,
        "desktop_read_failures": failures,
        "desktop_scan_capped": capped,
    }
    return pack(payload, desktop_entries + entries, limit=limit, max_bytes=max_bytes, more=capped)

_APP_COMMANDS = {
    "dpkg": (["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], "dpkg-query"),
    "snap": (["snap", "list", "--color=never", "--unicode=never"], "snap"),
    "flatpak": (["flatpak", "list", "--app", "--columns=application,version"], "flatpak"),
}
_APP_CURSOR = re.compile(r"a1\.([0-9a-f]{16})\.(0|[1-9][0-9]{0,5})\Z")


def _app_context(provider: str, name: str | None) -> str:
    key = f"{provider}\0{name.casefold() if name else ''}".encode()
    return hashlib.sha256(key).hexdigest()[:16]


def _app_cursor(context: str, offset: int) -> str:
    return f"a1.{context}.{offset}"


def _app_rows(stdout: bytes, provider: str, clipped: bool,
              needle: str | None) -> tuple[list[dict[str, Any]], int, int]:
    lines = stdout.decode("utf-8", "replace").splitlines()
    if clipped and lines:
        lines = lines[:-1]  # The final record may be incomplete.
    lines = [line for line in lines if line.strip()]
    if provider in {"snap", "flatpak"} and lines:
        heading = "Name" if provider == "snap" else "Application"
        if lines[0].split(maxsplit=1)[0] == heading:
            lines = lines[1:]
    rows: list[dict[str, Any]] = []
    malformed = 0
    entries_seen = 0
    for line in lines:
        if provider == "dpkg" or (provider == "flatpak" and "\t" in line):
            parts = line.split("\t", 1)
        elif provider == "snap":
            parts = line.split(maxsplit=2)
        else:
            parts = line.split(maxsplit=1)
        if not parts or not parts[0] or (provider == "dpkg" and len(parts) != 2):
            malformed += 1
            continue
        full_name = parts[0].strip()
        name = bounded_text(full_name, 128)
        version = bounded_text(parts[1].strip(), 128) if len(parts) > 1 else None
        if not name:
            malformed += 1
            continue
        entries_seen += 1
        if needle is not None and needle not in full_name.casefold():
            continue
        source = "dpkg-query" if provider == "dpkg" else provider
        value: dict[str, Any] = {"name": name, "version": version}
        if len(full_name) > 128:
            value["name_truncated"] = True
        rows.append(item(source, source, "ok", value))
    return rows, malformed, entries_seen


def query_apps(*, provider: str = "dpkg", name: str | None = None, cursor: str | None = None,
               limit: int = 10, max_bytes: int = 4096) -> dict[str, Any]:
    """On-demand, byte-capped package inventory for one explicitly chosen source.

    Cursor identifies a provider/filter context and offset into a fresh command
    result; entries can move between pages when the local inventory changes.
    """
    limits(limit, max_bytes)
    if provider not in _APP_COMMANDS:
        raise ObserveQueryError("provider must be dpkg, snap, or flatpak")
    if name is not None and (not isinstance(name, str) or not 1 <= len(name) <= 128
                             or not name.strip() or not name.isprintable()
                             or bounded_text(name, 128) != name):
        raise ObserveQueryError("name must be 1..128 printable characters")
    context = _app_context(provider, name)
    match = _APP_CURSOR.fullmatch(cursor) if isinstance(cursor, str) else None
    if cursor is not None and (match is None or match.group(1) != context
                               or int(match.group(2)) > 100_000):
        raise ObserveQueryError("invalid apps cursor for provider and name")
    offset = int(match.group(2)) if match else 0
    argv, source = _APP_COMMANDS[provider]
    payload = base("apps", {"provider": provider, "name": name, "cursor": cursor})
    try:
        stdout, stderr, returncode, clipped = _run(argv)
    except (OSError, TimeoutError) as exc:
        code = availability(exc)
        payload["coverage"] = {"availability": code, "source": source, "entries_seen": 0}
        payload["errors"].append(error(code, source))
        return pack(payload, [], limit=limit, max_bytes=max_bytes)
    if returncode and not clipped:
        message = stderr[:512].decode("utf-8", "replace").lower()
        if provider == "snap" and "no snaps are installed" in message:
            stdout = b""
        else:
            code = "permission_denied" if "permission denied" in message or "access denied" in message else "error"
            payload["coverage"] = {"availability": code, "source": source, "entries_seen": 0}
            payload["errors"].append(error(code, source, "inventory command exited with an error"))
            return pack(payload, [], limit=limit, max_bytes=max_bytes)
    needle = name.casefold() if name is not None else None
    matches, malformed, entries_seen = _app_rows(stdout, provider, clipped, needle)
    partial = clipped or bool(malformed)
    if clipped:
        payload["errors"].append(error("source_truncated", source))
    if malformed:
        payload["errors"].append(error("parse_error", source, f"{malformed} inventory rows skipped"))
    payload["coverage"] = {"availability": "partial" if partial else "ok", "source": source,
                           "entries_seen": entries_seen, "matches_seen": len(matches),
                           "malformed_rows": malformed,
                           "source_truncated": clipped,
                           "pagination": "live_offset"}
    selected = matches[offset:]
    cursors: list[str | None] = [
        _app_cursor(context, index + 1) if index + 1 < len(matches) else None
        for index in range(offset, offset + min(limit, len(selected)))
    ]
    return pack(payload, selected, limit=limit, max_bytes=max_bytes,
                next_cursors=cursors, more=clipped and bool(selected))


def query_drivers(*, limit: int = 10, max_bytes: int = 4096) -> dict[str, Any]:
    """Loaded kernel modules from procfs; presence does not imply active hardware."""
    limits(limit, max_bytes)
    payload = base("drivers")
    try:
        entries = []
        for line in _lines(MODULES):
            fields = line.split()
            if len(fields) < 3:
                continue
            entries.append(item(str(MODULES), "procfs", "ok",
                                {"module": bounded_text(fields[0], 128),
                                 "size_bytes": int(fields[1]), "use_count": int(fields[2])},
                                unit="bytes"))
        payload["coverage"] = {"availability": "ok", "modules_seen": len(entries)}
        return pack(payload, entries, limit=limit, max_bytes=max_bytes)
    except (OSError, ValueError) as exc:
        return _failure(payload, str(MODULES), exc, limit=limit, max_bytes=max_bytes)
