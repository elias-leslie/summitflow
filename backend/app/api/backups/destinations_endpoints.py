"""Read-only offsite destination status for the Backups page.

The restic repository checks and the Proxmox append-only copy record their
results in the backup safety status file; this exposes the parts the page shows
next to the nightly schedule window.
"""

from typing import Any

from fastapi import APIRouter

from ...config import settings
from ...tasks.backup_safety import read_status

router = APIRouter()


def _check(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {"checked_at": value.get("checked_at"), "status": value.get("status")}


def _alerts(section: Any) -> list[str]:
    if not isinstance(section, dict):
        return []
    return [str(alert.get("message")) for alert in section.get("alerts") or [] if isinstance(alert, dict) and alert.get("message")]


def destinations_status() -> dict[str, Any]:
    sections = read_status().get("sections") or {}
    checks_section = sections.get("restic_checks") or {}
    checks = checks_section.get("checks") or {}
    pve = sections.get("pve_copy")
    proxmox = None
    if isinstance(pve, dict):
        maintenance = pve.get("pve_maintenance") or {}
        check = _check(maintenance.get("check")) or {}
        proxmox = {
            "last_copy_at": pve.get("last_success_at"),
            "last_attempt_at": pve.get("last_attempt_at"),
            "error": pve.get("error"),
            "checked_at": check.get("checked_at"),
            "check_status": check.get("status"),
            "alerts": _alerts(pve),
        }
    return {
        "schedule_window": settings.backup_schedule_window,
        "schedule_timezone": settings.backup_schedule_timezone,
        "local_check": _check(checks.get("local")),
        "drive_check": _check(checks.get("remote")),
        "check_alerts": _alerts(checks_section),
        "proxmox": proxmox,
    }


@router.get("/backups/destinations")
async def backup_destinations() -> dict[str, Any]:
    return destinations_status()
