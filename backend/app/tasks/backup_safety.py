"""Deletion circuit breaker and the machine-readable backup safety status.

Every automatic removal of backup points (local and offsite restic retention,
native archive expiry, btrbk target expiry) asks ``guard_deletion`` first. A
plan that removes more than normal retention would (a large share of all
points, or of one source) is refused, recorded, and alerted; the caller keeps
the points and carries on backing up. An owner can approve one oversized run
with ``st backup storage approve-deletion``.

``STATUS_PATH`` is a stable JSON contract read by Nightshift and other
watchers: top-level ``status`` is ``ok`` or ``alert`` and ``alerts`` lists
each active condition with a plain message.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

STATUS_VERSION = 1
TOTAL_TRIP_FRACTION = 0.25
TOTAL_TRIP_MIN = 10
GROUP_TRIP_FRACTION = 0.5
GROUP_TRIP_MIN = 6
APPROVAL_HOURS = 24


def status_path() -> Path:
    override = os.environ.get("SUMMITFLOW_BACKUP_SAFETY_STATUS")
    if override:
        return Path(override)
    return Path.home() / ".local" / "state" / "summitflow" / "backup-safety" / "status.json"


def _now() -> datetime:
    return datetime.now(UTC)


@contextlib.contextmanager
def _locked_status() -> Iterator[dict[str, Any]]:
    """Read-modify-write the status file under a lock, replacing it atomically."""
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".status.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            status = json.loads(path.read_text())
            if not isinstance(status, dict):
                status = {}
        except (OSError, ValueError):
            status = {}
        status.setdefault("breakers", {})
        status.setdefault("approvals", {})
        status.setdefault("sections", {})
        yield status
        status["version"] = STATUS_VERSION
        status["updated_at"] = _now().isoformat()
        status["alerts"] = _active_alerts(status)
        status["status"] = "alert" if status["alerts"] else "ok"
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
        temporary.chmod(0o644)
        temporary.replace(path)


def _active_alerts(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    alerts = []
    for key, breaker in sorted((status.get("breakers") or {}).items()):
        if breaker.get("tripped"):
            alerts.append({"key": f"breaker:{key}", "kind": "deletion-breaker", "since": breaker.get("first_tripped_at"),
                           "message": f"Refused {breaker.get('kind')} deletion on {breaker.get('target')}: {'; '.join(breaker.get('reasons') or [])}"})
    for name, section in sorted((status.get("sections") or {}).items()):
        for alert in section.get("alerts") or []:
            alerts.append({"key": f"{name}:{alert.get('kind')}", "since": section.get("updated_at"), **alert})
    return alerts


def read_status() -> dict[str, Any]:
    try:
        value = json.loads(status_path().read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def evaluate_deletion(
    *, delete: int, total: int, groups: Mapping[str, tuple[int, int]] | None = None,
    total_fraction: float = TOTAL_TRIP_FRACTION, total_min: int = TOTAL_TRIP_MIN,
    group_fraction: float = GROUP_TRIP_FRACTION, group_min: int = GROUP_TRIP_MIN,
) -> list[str]:
    """Reasons a plan exceeds normal retention; ``groups`` maps name -> (delete, total)."""
    reasons = []
    if delete > total_min and total > 0 and delete / total > total_fraction:
        reasons.append(f"would remove {delete} of {total} points (> {total_fraction:.0%})")
    for name, (removed, available) in sorted((groups or {}).items()):
        if removed > group_min and available > 0 and removed / available > group_fraction:
            reasons.append(f"would remove {removed} of {available} points of {name} (> {group_fraction:.0%})")
    return reasons


def guard_deletion(kind: str, target: str, *, delete: int, total: int, groups: Mapping[str, tuple[int, int]] | None = None, **limits: Any) -> bool:
    """Return True when the deletion may proceed; record and alert when it may not."""
    reasons = evaluate_deletion(delete=delete, total=total, groups=groups, **limits)
    key = f"{kind}:{target}"
    now = _now()
    try:
        with _locked_status() as status:
            previous = status["breakers"].get(key) or {}
            approval = status["approvals"].get(kind) or status["approvals"].get(key) or {}
            approved = bool(reasons) and _approval_valid(approval, now)
            entry: dict[str, Any] = {"kind": kind, "target": target, "checked_at": now.isoformat(), "planned_delete": delete,
                     "total": total, "reasons": reasons, "tripped": bool(reasons) and not approved}
            if entry["tripped"]:
                entry["first_tripped_at"] = previous.get("first_tripped_at") or now.isoformat()
            if approved:
                entry["approved_by"] = approval.get("reason")
                status["approvals"].pop(kind, None)
                status["approvals"].pop(key, None)
            status["breakers"][key] = entry
    except OSError:
        logger.exception("backup_safety_status_write_failed", kind=kind, target=target)
        entry = {"tripped": bool(reasons), "reasons": reasons}
        previous = {}
    if entry["tripped"]:
        logger.warning("backup_deletion_breaker_tripped", kind=kind, target=target, reasons=reasons)
        if not previous.get("tripped"):
            _notify(kind, target, reasons)
        return False
    return True


def _approval_valid(approval: Mapping[str, Any], now: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(approval["expires_at"])) > now
    except (KeyError, ValueError, TypeError):
        return False


def approve_deletion(kind: str, *, target: str | None = None, reason: str, hours: int = APPROVAL_HOURS) -> dict[str, Any]:
    """Allow the next oversized run of ``kind`` (optionally one target) within ``hours``."""
    key = f"{kind}:{target}" if target else kind
    approval = {"reason": reason, "approved_at": _now().isoformat(), "expires_at": (_now() + timedelta(hours=hours)).isoformat()}
    with _locked_status() as status:
        status["approvals"][key] = approval
    return {"approval": key, **approval}


def record_section(name: str, payload: Mapping[str, Any]) -> None:
    """Replace one named status section (``pve_copy``, ``health``); ``alerts`` inside raise the top level."""
    try:
        with _locked_status() as status:
            status["sections"][name] = {**payload, "updated_at": _now().isoformat()}
    except OSError:
        logger.exception("backup_safety_status_write_failed", section=name)


def _notify(kind: str, target: str, reasons: list[str]) -> None:
    try:
        from ..storage.notifications import create_notification

        create_notification(
            project_id="summitflow", notification_type="system", title="Backup deletion refused",
            message=(f"A {kind} run on {target} would remove more backup points than normal retention, so nothing was removed. "
                     f"{'; '.join(reasons)}. Check retention settings; to allow this one run: st backup storage approve-deletion {kind}")[:2000],
            severity="error", metadata={"backup_breaker": kind, "target": target, "reasons": reasons},
            dedupe_key=f"backup-breaker:{kind}:{target}:{_now().date().isoformat()}",
        )
    except Exception:
        logger.warning("backup_breaker_notification_failed", kind=kind, target=target)
