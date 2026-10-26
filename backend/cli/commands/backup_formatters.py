"""Plain-text views for `st backup`: status, snapshot lists and what a snapshot holds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any


def format_size(size_bytes: int | float | None) -> str:
    """Bytes as 1.5 GB; a missing size is a dash."""
    if size_bytes is None:
        return "-"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "-"


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def local_time(value: Any) -> str:
    when = parse_time(value)
    return when.astimezone().strftime("%Y-%m-%d %H:%M") if when else "-"


def ago(value: Any, now: datetime | None = None) -> str:
    when = parse_time(value)
    if when is None:
        return "never"
    hours = ((now or datetime.now(UTC)) - when).total_seconds() / 3600
    if hours < 1:
        return f"{max(hours * 60, 0):.0f} minutes ago"
    return f"{hours:.0f} hours ago" if hours < 48 else f"{hours / 24:.0f} days ago"


def _local_section(local: Mapping[str, Any], now: datetime) -> list[str]:
    lines = [f"Local: {local['engine']} to the T7, {local['schedule']}, kept {local['keeps']}"]
    if not local.get("enabled"):
        lines.append("  Switched off.")
    last = local.get("last_run") or {}
    good = local.get("last_good_at")
    lines.append(f"  Last good point: {ago(good, now)}" + (f" ({local_time(good)})" if good else ""))
    if last.get("status") not in (None, "completed"):
        lines.append(f"  Last run: {last['status']}" + (f" - {last['error']}" if last.get("error") else ""))
    if local.get("next_run_at"):
        lines.append(f"  Next run: {local_time(local['next_run_at'])}")
    if local.get("points"):
        lines.append("  Points on the T7: " + ", ".join(f"{name} {count}" for name, count in local["points"].items()))
    target = local.get("target")
    if target:
        lines.append(f"  T7: {format_size(target['free_bytes'])} free of {format_size(target['total_bytes'])}")
    return lines


def _offsite_section(offsite: Mapping[str, Any], now: datetime) -> list[str]:
    lines = [f"Google Drive: {offsite['engine']}, {offsite['schedule']}"]
    if offsite.get("running"):
        lines.append(f"  Running now, started {ago(offsite['running'].get('started_at'), now)}")
    success = offsite.get("last_success_at")
    lines.append(f"  Last good run: {ago(success, now)}" + (f" ({local_time(success)})" if success else ""))
    if offsite.get("status") not in (None, "ok", "running"):
        lines.append(f"  Last run: {offsite['status']}" + (f" - {offsite['error']}" if offsite.get("error") else ""))
    jobs = offsite.get("jobs") or {}
    if jobs:
        lines.append("  Last good snapshot per job:")
        width = max(len(name) for name in jobs)
        for name, job in sorted(jobs.items()):
            lines.append(f"    {name:<{width}}  {ago(job.get('time'), now):<14} {job.get('snapshot_id', '-')[:8]}  "
                         f"{format_size(job.get('bytes'))} read, {format_size(job.get('stored_bytes'))} stored")
    check = offsite.get("check")
    if check:
        text = f"{check.get('status')}, {check.get('sample') or '?'} of stored data read back, {ago(check.get('checked_at'), now)}"
        text += " (ran out of time; reads another sample next week)" if check.get("status") == "partial" else ""
        lines.append(f"  Data check: {text}" + (f" - {check['error']}" if check.get("error") else ""))
    spot = offsite.get("spot_restore")
    if spot:
        lines.append(f"  Test restore: {spot.get('status')}, {ago(spot.get('at'), now)}" + (f" - {spot['error']}" if spot.get("error") else ""))
    maintenance = offsite.get("maintenance") or {}
    if maintenance.get("pruned_at"):
        lines.append(f"  Cleanup: last pruned {ago(maintenance['pruned_at'], now)}")
    return lines


def _old_section(legacy: Mapping[str, Any]) -> list[str]:
    repo = legacy.get("local_repository") or {}
    drive = legacy.get("drive_snapshots") or {}
    lines = ["Old backups (from before the daily job; nothing writes to them any more)"]
    if repo.get("path"):
        lines.append(f"  T7 restic repository: {repo['path']}, {format_size(repo.get('bytes'))}. You can delete it.")
    if drive.get("count"):
        lines.append(f"  Google Drive: {drive['count']} per-project snapshots, gone {drive.get('ages_out_after_days')} days after the change")
    return lines if len(lines) > 1 else []


def render_status(overview: Mapping[str, Any], now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    problems = overview.get("problems") or []
    if problems:
        lines = [f"{len(problems)} backup problem{'s' if len(problems) != 1 else ''}:"]
        lines += [f"  {item['title']}: {item['message']}" for item in problems]
    else:
        lines = ["All backups current."]
    for section in (_local_section(overview["local"], now), _offsite_section(overview["offsite"], now), _old_section(overview.get("legacy") or {})):
        if section:
            lines += ["", *section]
    return "\n".join(lines)


def render_snapshots(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "No snapshots found."
    lines = [f"{'ID':<9} {'TIME':<17} {'JOB':<12} {'BTRBK RUN':<22} PATHS"]
    for row in rows:
        paths = ", ".join(row.get("paths") or [])
        lines.append(f"{row['id']:<9} {local_time(row['time']):<17} {row.get('job') or '-':<12} {row.get('btrbk_run') or '-':<22} {paths[:60]}")
    return "\n".join(lines)


def render_old_snapshots(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "No old snapshots found."
    lines = [f"{'ID':<9} {'TIME':<17} SOURCE"]
    lines += [f"{row['id']:<9} {local_time(row['time']):<17} {row.get('source') or '-'}" for row in rows]
    return "\n".join(lines)


def render_job_record(name: str, job: Mapping[str, Any], now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    return [
        f"{name}: snapshot {job.get('snapshot_id', '-')[:8]}, {ago(job.get('time'), now)} ({local_time(job.get('time'))})",
        f"  Tags: {', '.join(job.get('tags') or []) or '-'}",
        f"  Read {job.get('files', 0)} files, {format_size(job.get('bytes'))}; added {format_size(job.get('added_bytes'))}, "
        f"stored {format_size(job.get('stored_bytes'))}",
    ]


def render_contents(snapshot: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], *, base: str, note: str | None = None) -> str:
    """One snapshot and what sits directly under ``base`` in it, largest first."""
    lines = [
        f"Snapshot {snapshot['id']} from {local_time(snapshot['time'])}",
        f"  Tags: {', '.join(snapshot.get('tags') or []) or '-'}",
        f"  Paths: {', '.join(snapshot.get('paths') or []) or '-'}",
        f"  Contents of {base}:",
    ]
    ranked = sorted(entries, key=lambda item: item.get("bytes") or 0, reverse=True)
    for item in ranked[:25]:
        count = f", {item['files']} files" if item.get("files") is not None else ""
        lines.append(f"    {item['name']:<36} {format_size(item.get('bytes')):>10}{count}")
    if len(ranked) > 25:
        lines.append(f"    ... and {len(ranked) - 25} more")
    if note:
        lines.append(f"  {note}")
    return "\n".join(lines)
