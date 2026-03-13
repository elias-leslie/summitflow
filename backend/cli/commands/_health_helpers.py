"""Helper functions for health CLI commands."""

from __future__ import annotations

from typing import Any


def format_health_compact(health: dict[str, Any]) -> None:
    """Format health summary in TOON style.

    Format:
    HEALTH:{project_id}:{PASS|FAIL}:unfixed={N}
    {check_type}:{PASS|FAIL}:err={N}|warn={N}|last={timestamp}
    """
    project_id = health.get("project_id", "unknown")
    overall = "PASS" if health.get("overall_pass") else "FAIL"
    unfixed = health.get("total_unfixed", 0)

    print(f"HEALTH:{project_id}:{overall}:unfixed={unfixed}")

    checks = health.get("checks", {})
    for check_type, details in checks.items():
        status = "PASS" if details.get("status") == "pass" else "FAIL"
        errors = details.get("error_count", 0)
        warnings = details.get("warning_count", 0)
        last_run = details.get("last_run", "never")
        if last_run != "never":
            # Truncate timestamp to just date/time
            last_run = last_run[:19] if len(last_run) > 19 else last_run
        print(f"  {check_type}:{status}:err={errors}|warn={warnings}|last={last_run}")


def format_results_compact(results: dict[str, Any]) -> None:
    """Format check results in TOON style.

    Format:
    RESULTS[N]:unfixed={M}
    {id} {check_type:6} {status:4} {file}:{line} {message:50}
    """
    items = results.get("items", [])
    unfixed = results.get("unfixed_count", 0)

    print(f"RESULTS[{len(items)}]:unfixed={unfixed}")

    for item in items:
        result_id = item.get("id", "?")
        check_type = (item.get("check_type") or "")[:6].ljust(6)
        status = (item.get("status") or "")[:4].ljust(4)
        file_path = item.get("file_path") or "-"
        line = item.get("line_number") or "-"
        loc = f"{file_path}:{line}"
        if len(loc) > 40:
            loc = "..." + loc[-37:]
        loc = loc.ljust(40)
        message = item.get("error_message") or "-"
        if len(message) > 50:
            message = message[:47] + "..."
        print(f"  {result_id} {check_type} {status} {loc} {message}")


def build_sync_payload(
    check_type: str,
    status_val: str,
    error_count: int,
    warning_count: int,
    triggered_by: str,
) -> dict[str, Any]:
    """Build the JSON payload for the sync API call."""
    return {
        "check_type": check_type,
        "status": status_val,
        "error_count": error_count,
        "warning_count": warning_count,
        "triggered_by": triggered_by,
    }


def print_sync_compact(data: dict[str, Any], check_type: str, status_val: str) -> None:
    """Print sync result in compact TOON style."""
    synced = data.get("synced", False)
    created = data.get("created_count", 0)
    ct = data.get("check_type", check_type)
    st = data.get("status", status_val)
    status_word = "OK" if synced else "FAIL"
    print(f"SYNC:{status_word}:{ct}:{st}:created={created}")


def build_results_query(limit: int, check_type: str | None, status_filter: str | None, unfixed: bool) -> str:
    """Build the query string for the results API endpoint."""
    params = [f"limit={limit}"]
    if check_type:
        params.append(f"check_type={check_type}")
    if status_filter:
        params.append(f"status={status_filter}")
    if unfixed:
        params.append("unfixed_only=true")
    return "&".join(params)
