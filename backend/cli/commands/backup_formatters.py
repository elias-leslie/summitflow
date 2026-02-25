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


def format_compact_source(source: dict[str, Any]) -> str:
    """Format source as compact one-liner.

    Format: <id:20> <type:10> <enabled:8> <frequency:8> <retention:4> <name>
    """
    source_id = (source.get("id") or "?")[:20].ljust(20)
    source_type = (source.get("source_type") or "?")[:10].ljust(10)
    enabled = "enabled" if source.get("enabled") else "disabled"
    enabled = enabled[:8].ljust(8)
    freq = (source.get("frequency") or "?")[:8].ljust(8)
    ret = str(source.get("retention_days", "?"))[:4].ljust(4)
    name = source.get("name") or "?"
    return f"{source_id} {source_type} {enabled} {freq} {ret} {name}"


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


def output_sources(out: OutputContext, sources: list[dict[str, Any]]) -> None:
    """Output backup sources list."""
    if out.is_compact:
        print(f"SOURCES[{len(sources)}]")
        for s in sources:
            print(format_compact_source(s))
    else:
        output_json({"sources": sources, "total": len(sources)})


def output_source(out: OutputContext, source: dict[str, Any]) -> None:
    """Output a single backup source."""
    if out.is_compact:
        print(format_compact_source(source))
    else:
        output_json(source)


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
