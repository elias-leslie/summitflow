"""Host pressure checks for runtime hygiene."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .runtime_hygiene_common import (
    CPU_CRIT_PERCENT,
    CPU_WARN_PERCENT,
    DISK_CRIT_FREE_GB,
    DISK_CRIT_PERCENT,
    DISK_REMEDIATE_FREE_GB,
    DISK_WARN_PERCENT,
    HOST_SCOPE,
    MEMORY_CRIT_PERCENT,
    MEMORY_WARN_PERCENT,
    ROOT_MOUNT,
    Severity,
    normalize_action_status,
    record_action,
)


def collect_host_snapshot(*, include_top_processes: bool, deps: Any) -> dict[str, Any]:
    disks = _mount_map(deps)
    root_disk = disks.get(ROOT_MOUNT) or _unknown_root_disk()
    summary = {
        "disk": root_disk,
        "disks": list(disks.values()),
        "memory": deps.get_memory_usage(),
        "cpu": deps.get_cpu_usage(),
    }
    if include_top_processes:
        summary["top_processes"] = _collect_top_processes(deps=deps)
    return summary


def host_pressure(
    *,
    latest_runtime_hygiene: dict[str, Any] | None,
    now: datetime,
    deps: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    host = deps._collect_host_snapshot(include_top_processes=False)
    actions_taken: list[dict[str, Any]] = []
    if _has_root_pressure(host["disk"]):
        host = _handle_root_pressure(host, actions_taken, now, deps)

    issues = _host_resource_issues(host, deps)
    _enrich_top_processes(host, issues, deps)
    created_task_ids, reused_task_ids = deps.persist_issues(issues, deps)
    return host, actions_taken, issues, created_task_ids, reused_task_ids


def _mount_map(deps: Any) -> dict[str, dict[str, Any]]:
    return {
        str(item["mount_path"]): {
            "label": item.get("label"),
            "mount_path": item.get("mount_path"),
            "total_gb": item.get("total_gb"),
            "used_gb": item.get("used_gb"),
            "free_gb": item.get("free_gb"),
            "percent_used": item.get("percent_used"),
            "status": item.get("status"),
        }
        for item in deps.get_disk_usages()
    }


def _collect_top_processes(limit: int = 5, *, deps: Any) -> list[dict[str, Any]]:
    try:
        processes = list(deps.psutil.process_iter(["pid", "name", "username", "memory_info", "cmdline"]))
        _prime_cpu_percent(processes, deps)
        time.sleep(0.1)
        procs = [_process_snapshot(proc, deps) for proc in processes]
    except Exception:
        deps.logger.exception("runtime_hygiene_top_processes_failed")
        return []
    return sorted([proc for proc in procs if proc], key=_process_sort_key, reverse=True)[:limit]


def _prime_cpu_percent(processes: list[Any], deps: Any) -> None:
    for proc in processes:
        try:
            proc.cpu_percent(None)
        except (deps.psutil.NoSuchProcess, deps.psutil.AccessDenied):
            continue


def _process_snapshot(proc: Any, deps: Any) -> dict[str, Any] | None:
    try:
        info = proc.as_dict(attrs=["pid", "name", "username", "memory_info", "cmdline"])
        rss = int(getattr(info.get("memory_info"), "rss", 0) or 0)
        cmdline = info.get("cmdline") or []
        return {
            "pid": info.get("pid"),
            "name": info.get("name") or "unknown",
            "user": info.get("username") or "unknown",
            "cpu_percent": round(float(proc.cpu_percent(None)), 2),
            "rss_mb": round(rss / (1024 * 1024), 1),
            "cmd": " ".join(str(part) for part in cmdline[:6])[:180],
        }
    except (deps.psutil.NoSuchProcess, deps.psutil.AccessDenied):
        return None


def _process_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    return item["cpu_percent"], item["rss_mb"]


def _unknown_root_disk() -> dict[str, Any]:
    return {
        "label": "Root",
        "mount_path": ROOT_MOUNT,
        "total_gb": 0.0,
        "used_gb": 0.0,
        "free_gb": 0.0,
        "percent_used": 0.0,
        "status": "unknown",
    }


def _has_root_pressure(root_disk: dict[str, Any]) -> bool:
    return (
        float(root_disk.get("percent_used") or 0.0) >= DISK_WARN_PERCENT
        or float(root_disk.get("free_gb") or 0.0) <= DISK_REMEDIATE_FREE_GB
    )


def _handle_root_pressure(
    host: dict[str, Any],
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    if deps._run_started_within("daily_maintenance", hours=6.0, now=now):
        _record_cleanup_skip(actions_taken)
        return host
    cleanup_result = deps.cleanup_host_artifacts()
    record_action(
        actions_taken,
        action_type="host_cleanup",
        scope=HOST_SCOPE,
        fingerprint="host:root",
        status=normalize_action_status(cleanup_result.get("status")),
        detail="Ran host artifact cleanup",
        result=cleanup_result,
    )
    refreshed = deps._collect_host_snapshot(include_top_processes=False)
    refreshed["cleanup"] = cleanup_result
    return refreshed


def _record_cleanup_skip(actions_taken: list[dict[str, Any]]) -> None:
    record_action(
        actions_taken,
        action_type="host_cleanup",
        scope=HOST_SCOPE,
        fingerprint="host:root",
        status="skipped",
        detail="Skipped host cleanup because daily_maintenance ran within the last 6 hours",
    )


def _host_resource_issues(host: dict[str, Any], deps: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    _append_disk_issue(host, issues, deps)
    _append_memory_issue(host, issues, deps)
    _append_cpu_issue(host, issues, deps)
    return issues


def _append_disk_issue(host: dict[str, Any], issues: list[dict[str, Any]], deps: Any) -> None:
    root_disk = host["disk"]
    disk_percent = float(root_disk.get("percent_used") or 0.0)
    root_free_gb = float(root_disk.get("free_gb") or 0.0)
    if disk_percent < DISK_WARN_PERCENT and root_free_gb > DISK_REMEDIATE_FREE_GB:
        return
    severity: Severity = "critical" if disk_percent >= DISK_CRIT_PERCENT or root_free_gb <= DISK_CRIT_FREE_GB else "warning"
    issues.append(
        deps.host_issue(
            "resource",
            "root-disk",
            severity,
            f"Root disk pressure remains at {root_disk.get('percent_used')}% used with {root_disk.get('free_gb')} GiB free",
            {"disk": root_disk, "cleanup": host.get("cleanup")},
        )
    )


def _append_memory_issue(host: dict[str, Any], issues: list[dict[str, Any]], deps: Any) -> None:
    memory = host["memory"]
    percent = float(memory.get("percent_used") or 0.0)
    if percent < MEMORY_WARN_PERCENT:
        return
    severity: Severity = "critical" if percent >= MEMORY_CRIT_PERCENT else "warning"
    issues.append(deps.host_issue("resource", "memory", severity, f"Host memory pressure is {percent}% used", {"memory": memory}))


def _append_cpu_issue(host: dict[str, Any], issues: list[dict[str, Any]], deps: Any) -> None:
    cpu = host["cpu"]
    percent = float(cpu.get("percent_used") or 0.0)
    if percent < CPU_WARN_PERCENT:
        return
    severity: Severity = "critical" if percent >= CPU_CRIT_PERCENT else "warning"
    issues.append(deps.host_issue("resource", "cpu", severity, f"Host CPU pressure is {percent}% used", {"cpu": cpu}))


def _enrich_top_processes(host: dict[str, Any], issues: list[dict[str, Any]], deps: Any) -> None:
    if not any(item["fingerprint"] in {"memory", "cpu"} for item in issues):
        return
    host["top_processes"] = _collect_top_processes(deps=deps)
    for item in issues:
        if item["fingerprint"] in {"memory", "cpu"}:
            item["evidence"]["top_processes"] = host["top_processes"]
