"""Backup formatting utilities."""

from __future__ import annotations

from typing import Any

from ..output import output_json
from ..output_context import OutputContext


def format_size(size_bytes: int | None) -> str:
    """Format bytes to human readable."""
    if size_bytes is None or size_bytes == 0:
        return "-"
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def format_compact_backup(backup: dict[str, Any]) -> str:
    """Format backup as compact one-liner.

    Format: <id> <status:9> <size:8> <created> <note:30>
    """
    backup_id = backup.get("id", "?")
    status = (backup.get("status") or "pending")[:9].ljust(9)
    size = format_size(backup.get("size_bytes"))[:8].ljust(8)
    created = backup.get("created_at", "")[:10]  # Just date
    note = (backup.get("note") or "-")[:30]
    return f"{backup_id} {status} {size} {created} {note}"


def output_backups(out: OutputContext, backups: list[dict[str, Any]], total: int) -> None:
    """Output backup list."""
    if out.is_compact:
        print(f"BACKUPS[{total}]")
        for b in backups:
            print(format_compact_backup(b))
    else:
        output_json({"backups": backups, "total": total})


def output_backup(out: OutputContext, backup: dict[str, Any]) -> None:
    """Output a single backup."""
    if out.is_compact:
        print(format_compact_backup(backup))
    else:
        output_json(backup)


def output_schedule(out: OutputContext, schedule: dict[str, Any] | None) -> None:
    """Output backup schedule."""
    if schedule is None:
        if out.is_compact:
            print("SCHEDULE disabled")
        else:
            output_json({"enabled": False, "message": "No schedule configured"})
    else:
        if out.is_compact:
            enabled = "enabled" if schedule.get("enabled") else "disabled"
            freq = schedule.get("frequency", "?")
            ret = schedule.get("retention_count", "?")
            next_run = (schedule.get("next_run_at") or "?")[:10]
            print(f"SCHEDULE {enabled}|{freq}|retention:{ret}|next:{next_run}")
        else:
            output_json(schedule)


def output_task_queued(out: OutputContext, task_id: str) -> None:
    """Output task queued message."""
    if out.is_compact:
        print(f"QUEUED {task_id}")
    else:
        output_json({"task_id": task_id})


def output_deleted(out: OutputContext, backup_id: str) -> None:
    """Output backup deleted message."""
    if out.is_compact:
        print(f"DELETED {backup_id}")
    else:
        output_json({"id": backup_id, "deleted": True})
