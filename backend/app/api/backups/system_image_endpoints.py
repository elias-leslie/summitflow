"""Host system-image backup endpoints backed by Veeam Agent for Linux."""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ...utils import safe_subprocess
from .models import (
    SystemImageActionResponse,
    SystemImageBackupStatus,
    SystemImageSession,
)

router = APIRouter()

JOB_NAME = "SummitFlowSystemImage"
REPOSITORY_NAME = "SummitFlowSystemImage"
REPOSITORY_PATH = "/media/kasadis/Backups/davion-gem/system-images/davion-sidarli-linux"
MOK_CERT_PATH = "/var/lib/shim-signed/mok/MOK.der"
ACTIVE_SESSION_STATES = {"Running", "Pending"}


def _run(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return safe_subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _run_sudo(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return _run(["sudo", "-n", *args], timeout=timeout)


def _veeam(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return _run_sudo(["veeamconfig", *args], timeout=timeout)


def _safe_text(proc: subprocess.CompletedProcess[str] | None) -> str:
    if proc is None:
        return ""
    return "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part and part.strip())


def _safe_command(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return _run(args, timeout=timeout)
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return None


def _safe_sudo_command(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return _run_sudo(args, timeout=timeout)
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
        return None


def _installed_version() -> str | None:
    proc = _safe_command(["dpkg-query", "-W", "-f=${Status}|${Version}", "veeam"])
    if not proc or proc.returncode != 0:
        return None
    status, _, version = proc.stdout.partition("|")
    if status.strip() != "install ok installed":
        return None
    return version.strip() or None


def _service_active() -> bool:
    proc = _safe_command(["systemctl", "is-active", "veeamservice"])
    return bool(proc and proc.returncode == 0 and proc.stdout.strip() == "active")


def _secure_boot_enabled() -> bool:
    proc = _safe_command(["mokutil", "--sb-state"])
    return bool(proc and "enabled" in proc.stdout.lower())


def _mok_enrolled() -> bool:
    proc = _safe_sudo_command(["mokutil", "--test-key", MOK_CERT_PATH])
    text = _safe_text(proc).lower()
    return "already enrolled" in text


def _mok_enrollment_pending() -> bool:
    proc = _safe_sudo_command(["mokutil", "--list-new"])
    return bool(proc and Path(MOK_CERT_PATH).exists() and "davion-sidarli" in proc.stdout)


def _module_loaded() -> bool:
    proc = _safe_command(["lsmod"])
    if not proc or proc.returncode != 0:
        return False
    return any(line.startswith("veeamblksnap ") for line in proc.stdout.splitlines())


def _module_signer() -> str | None:
    proc = _safe_command(["modinfo", "veeamblksnap"])
    if not proc or proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("signer:"):
            return line.split(":", 1)[1].strip() or None
    return None


def _split_table_line(line: str) -> list[str]:
    return [part.strip() for part in re.split(r"\s{2,}", line.strip()) if part.strip()]


def _clean_id(raw: str) -> str:
    return raw.strip().strip("{}")


def _repository_status() -> tuple[bool, bool]:
    proc = _veeam(["repository", "list"])
    if proc.returncode != 0:
        return False, False
    for line in proc.stdout.splitlines():
        parts = _split_table_line(line)
        if len(parts) >= 5 and parts[0] == REPOSITORY_NAME:
            return True, parts[4].lower() == "true"
    return False, False


def _job_info() -> tuple[bool, str | None, str | None, list[str]]:
    list_proc = _veeam(["job", "list"])
    if list_proc.returncode != 0:
        return False, None, None, []

    job_id = None
    for line in list_proc.stdout.splitlines():
        parts = _split_table_line(line)
        if len(parts) >= 4 and parts[0] == JOB_NAME:
            job_id = _clean_id(parts[1])
            break
    if job_id is None:
        return False, None, None, []

    info_proc = _veeam(["job", "info", "--name", JOB_NAME])
    schedule_summary = None
    protected_objects: list[str] = []
    if info_proc.returncode == 0:
        schedule_summary = _schedule_summary(info_proc.stdout)
        protected_objects = _protected_objects(info_proc.stdout)
    return True, job_id, schedule_summary, protected_objects


def _schedule_summary(output: str) -> str | None:
    lines = [line.strip() for line in output.splitlines()]
    daily = "Every day" in lines
    at = next((line.split(":", 1)[1].strip() for line in lines if line.startswith("At:")), None)
    active_full = next((line for line in lines if line.startswith("Active full:")), None)
    parts = []
    if daily and at:
        parts.append(f"Daily at {at}")
    elif daily:
        parts.append("Daily")
    if active_full:
        parts.append(active_full.replace("Active full: ", "Active full "))
    return "; ".join(parts) if parts else None


def _protected_objects(output: str) -> list[str]:
    objects = []
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Include Disk:"):
            objects.append(stripped.split(":", 1)[1].strip())
    return objects


def _sessions() -> list[SystemImageSession]:
    proc = _veeam(["session", "list"])
    if proc.returncode != 0:
        return []
    sessions = []
    for line in proc.stdout.splitlines():
        parts = _split_table_line(line)
        if len(parts) < 5 or parts[0] != JOB_NAME:
            continue
        sessions.append(
            SystemImageSession(
                job_name=parts[0],
                session_type=parts[1],
                id=_clean_id(parts[2]),
                state=parts[3],
                created_at=parts[4] if len(parts) > 4 else None,
                started_at=parts[5] if len(parts) > 5 else None,
                finished_at=parts[6] if len(parts) > 6 else None,
            )
        )
    return sorted(
        sessions,
        key=lambda session: (
            session.created_at or "",
            session.started_at or "",
            session.finished_at or "",
            session.id,
        ),
        reverse=True,
    )


def _status_sync() -> SystemImageBackupStatus:
    version = _installed_version()
    installed = version is not None
    service_active = _service_active()
    secure_boot_enabled = _secure_boot_enabled()
    mok_enrolled = _mok_enrolled()
    mok_enrollment_pending = _mok_enrollment_pending()
    module_loaded = _module_loaded()
    module_signer = _module_signer()
    repository_configured, repository_accessible = _repository_status() if installed else (False, False)
    job_configured, job_id, schedule_summary, protected_objects = (
        _job_info() if installed else (False, None, None, [])
    )
    sessions = _sessions() if installed else []
    active_session = next((s for s in sessions if s.state in ACTIVE_SESSION_STATES), None)
    last_session = sessions[0] if sessions else None

    blocked_reason = _blocked_reason(
        installed=installed,
        service_active=service_active,
        secure_boot_enabled=secure_boot_enabled,
        mok_enrolled=mok_enrolled,
        mok_enrollment_pending=mok_enrollment_pending,
        module_loaded=module_loaded,
        repository_configured=repository_configured,
        repository_accessible=repository_accessible,
        job_configured=job_configured,
        active_session=active_session,
    )
    can_start = blocked_reason is None and active_session is None

    return SystemImageBackupStatus(
        installed=installed,
        version=version,
        service_active=service_active,
        secure_boot_enabled=secure_boot_enabled,
        mok_enrolled=mok_enrolled,
        mok_enrollment_pending=mok_enrollment_pending,
        module_loaded=module_loaded,
        module_signer=module_signer,
        repository_name=REPOSITORY_NAME,
        repository_path=REPOSITORY_PATH,
        repository_accessible=repository_accessible,
        job_name=JOB_NAME,
        job_configured=job_configured,
        job_id=job_id,
        schedule_summary=schedule_summary,
        protected_objects=protected_objects,
        last_session=last_session,
        active_session=active_session,
        can_start=can_start,
        blocked_reason=blocked_reason,
        next_action=_next_action(blocked_reason, active_session),
    )


def _blocked_reason(
    *,
    installed: bool,
    service_active: bool,
    secure_boot_enabled: bool,
    mok_enrolled: bool,
    mok_enrollment_pending: bool,
    module_loaded: bool,
    repository_configured: bool,
    repository_accessible: bool,
    job_configured: bool,
    active_session: SystemImageSession | None,
) -> str | None:
    if not installed:
        return "Veeam Agent is not installed."
    if not service_active:
        return "Veeam service is not active."
    if not repository_configured:
        return "Veeam system-image repository is not configured."
    if not repository_accessible:
        return "Veeam system-image repository is not accessible."
    if not job_configured:
        return "Veeam system-image job is not configured."
    if secure_boot_enabled and not mok_enrolled and not module_loaded:
        if mok_enrollment_pending:
            return "Secure Boot is waiting for MOK enrollment at next reboot."
        return "Secure Boot blocks the Veeam kernel module until its MOK is enrolled."
    if active_session is not None:
        return "A system-image backup session is already active."
    return None


def _next_action(blocked_reason: str | None, active_session: SystemImageSession | None) -> str:
    if active_session is not None:
        return "Monitor or stop the active session."
    if blocked_reason:
        return blocked_reason
    return "Ready to start; scheduled daily at 02:00."


@router.get("/backups/system-image", response_model=SystemImageBackupStatus)
async def system_image_status() -> SystemImageBackupStatus:
    """Return Veeam host image backup status."""
    return await asyncio.to_thread(_status_sync)


@router.post("/backups/system-image/start", response_model=SystemImageActionResponse)
async def start_system_image_backup() -> SystemImageActionResponse:
    """Start the Veeam host image backup job."""
    status = await asyncio.to_thread(_status_sync)
    if not status.can_start:
        raise HTTPException(status_code=409, detail=status.blocked_reason or "Backup cannot start.")

    proc = await asyncio.to_thread(_veeam, ["job", "start", "--name", JOB_NAME], timeout=30)
    text = _safe_text(proc)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=text or "Failed to start backup.")
    match = re.search(r"Session ID:\s*\[\{([^}]+)\}\]", text)
    return SystemImageActionResponse(
        status="started",
        message="System-image backup started.",
        session_id=match.group(1) if match else None,
        output=text,
    )


@router.post("/backups/system-image/stop", response_model=SystemImageActionResponse)
async def stop_system_image_backup() -> SystemImageActionResponse:
    """Stop the active Veeam host image backup session."""
    status = await asyncio.to_thread(_status_sync)
    if status.active_session is None:
        raise HTTPException(status_code=409, detail="No active system-image backup session.")

    proc = await asyncio.to_thread(
        _veeam,
        ["session", "stop", "--id", status.active_session.id],
        timeout=30,
    )
    text = _safe_text(proc)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=text or "Failed to stop backup.")
    return SystemImageActionResponse(
        status="stopped",
        message="System-image backup stop requested.",
        session_id=status.active_session.id,
        output=text,
    )
