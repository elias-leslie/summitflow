#!/usr/bin/env python3
"""Weekly maintenance for the append-only restic copy, run only inside the CT.

The workstation can append but never delete, so retention lives here. Every
run: detect unexplained snapshot loss, plan per-source retention (same windows
as SummitFlow, never below MIN_DAYS, newest three per source always kept),
refuse any plan that removes more than normal retention would, then forget,
prune and read a rotating 1/12 data subset. Results go to STATUS_PATH, which
the workstation reads through the restricted key (`ssh ... status`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = os.environ.get("RESTIC_APPEND_REPO", "/srv/restic/repo")
PASSWORD_FILE = os.environ.get("RESTIC_APPEND_PASSWORD_FILE", "/etc/restic-append/password")
POLICY_PATH = Path(os.environ.get("RESTIC_APPEND_POLICY", "/etc/restic-append/policy.json"))
STATUS_PATH = Path(os.environ.get("RESTIC_APPEND_STATUS", "/var/lib/restic-append/status.json"))
RESTIC = os.environ.get("RESTIC_BIN", "/usr/local/bin/restic")
MIN_DAYS = 7
KEEP_LAST = 3
# Circuit breaker: normal weekly expiry removes a small slice. Anything larger
# means a policy mistake or clock jump, so nothing is removed and it alerts.
TOTAL_TRIP_FRACTION = 0.25
TOTAL_TRIP_MIN = 10
SOURCE_TRIP_FRACTION = 0.5
SOURCE_TRIP_MIN = 6
LOSS_TRIP_FRACTION = 0.10
CHECK_BUCKETS = 12


def _parse(value: str) -> datetime:
    # restic prints nanoseconds; fromisoformat accepts at most microseconds.
    text = value.replace("Z", "+00:00")
    if "." in text:
        head, rest = text.split(".", 1)
        digits = "".join(ch for ch in rest if ch.isdigit())
        text = f"{head}.{digits[:6]}{rest[len(digits):]}"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _source(snapshot: dict[str, Any]) -> str | None:
    sources = [str(tag)[7:] for tag in snapshot.get("tags") or [] if str(tag).startswith("source:")]
    return sources[0] if len(sources) == 1 else None


def plan_retention(snapshots: list[dict[str, Any]], policy: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Pure selection: delete only snapshots outside their source window and not newest three."""
    default_days = max(MIN_DAYS, int(policy.get("default_days", 30)))
    windows = {str(key): max(MIN_DAYS, int(value)) for key, value in (policy.get("sources") or {}).items()}
    groups: dict[str, list[tuple[datetime, str]]] = {}
    keep: set[str] = set()
    for snapshot in snapshots:
        source = _source(snapshot)
        if source is None:
            keep.add(snapshot["id"])  # Unmanaged or multi-source points stay forever.
            continue
        groups.setdefault(source, []).append((_parse(snapshot["time"]), snapshot["id"]))
    delete: list[str] = []
    per_source: dict[str, dict[str, int]] = {}
    for source, items in groups.items():
        cutoff = now - timedelta(days=windows.get(source, default_days))
        ordered = sorted(items, reverse=True)
        removed = [sid for index, (created, sid) in enumerate(ordered) if index >= KEEP_LAST and created < cutoff]
        delete.extend(removed)
        per_source[source] = {"total": len(items), "delete": len(removed)}
    return {"delete": sorted(delete), "total": len(snapshots), "per_source": per_source}


def breaker(plan: dict[str, Any]) -> list[str]:
    """Reasons to refuse a plan; empty means it is within normal retention."""
    reasons = []
    total, count = plan["total"], len(plan["delete"])
    if count > TOTAL_TRIP_MIN and total and count / total > TOTAL_TRIP_FRACTION:
        reasons.append(f"plan removes {count} of {total} snapshots (> {TOTAL_TRIP_FRACTION:.0%})")
    for source, item in sorted(plan["per_source"].items()):
        if item["delete"] > SOURCE_TRIP_MIN and item["delete"] / item["total"] > SOURCE_TRIP_FRACTION:
            reasons.append(f"plan removes {item['delete']} of {item['total']} snapshots of {source} (> {SOURCE_TRIP_FRACTION:.0%})")
    return reasons


def unexplained_loss(previous_count: int | None, current: int) -> str | None:
    if not previous_count:
        return None
    lost = previous_count - current
    if lost > TOTAL_TRIP_MIN and lost / previous_count > LOSS_TRIP_FRACTION:
        return f"snapshot count fell from {previous_count} to {current} since the last maintenance run"
    return None


def _restic(*args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    command = [RESTIC, "--repo", REPO, "--password-file", PASSWORD_FILE, "--no-cache", *args]
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def _save(status: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o644)
    temporary.replace(STATUS_PATH)


def main() -> int:
    now = datetime.now(UTC)
    previous = _load(STATUS_PATH)
    status: dict[str, Any] = {"version": 1, "repository": REPO, "started_at": now.isoformat(), "alerts": [],
                              "check": previous.get("check") or {}, "breaker": {"tripped": False}}
    snapshot_count = previous.get("snapshot_count")
    try:
        snapshots = json.loads(_restic("snapshots", "--json").stdout) or []
        status["snapshot_count_before"] = len(snapshots)
        loss = unexplained_loss(previous.get("snapshot_count"), len(snapshots))
        policy = _load(POLICY_PATH)
        plan = plan_retention(snapshots, policy, now)
        reasons = ([loss] if loss else []) + breaker(plan)
        status["plan"] = {"delete": len(plan["delete"]), "total": plan["total"]}
        if reasons:
            # Keep the old baseline so the condition stays visible until resolved.
            status["breaker"] = {"tripped": True, "reasons": reasons, "at": now.isoformat()}
            status["alerts"].append({"kind": "deletion-breaker", "message": "; ".join(reasons)})
            status["forget"] = {"status": "refused"}
            status["prune"] = {"status": "skipped", "reason": "deletion-breaker"}
        else:
            for start in range(0, len(plan["delete"]), 200):
                _restic("forget", *plan["delete"][start:start + 200])
            status["forget"] = {"status": "completed", "removed": len(plan["delete"])}
            if plan["delete"]:
                _restic("prune", "--max-unused", "5%")
                status["prune"] = {"status": "completed"}
            else:
                status["prune"] = {"status": "skipped", "reason": "nothing-forgotten"}
            snapshot_count = len(snapshots) - len(plan["delete"])
        bucket = int(status["check"].get("next_bucket", 1))
        try:
            _restic("check", f"--read-data-subset={bucket}/{CHECK_BUCKETS}")
            status["check"] = {"status": "verified", "bucket": bucket, "next_bucket": bucket % CHECK_BUCKETS + 1,
                               "checked_at": datetime.now(UTC).isoformat()}
        except subprocess.CalledProcessError as exc:
            status["check"] = {"status": "failed", "bucket": bucket, "next_bucket": bucket,
                               "error": (exc.stderr or "")[-500:], "checked_at": datetime.now(UTC).isoformat()}
            status["alerts"].append({"kind": "check-failed", "message": f"restic check bucket {bucket}/{CHECK_BUCKETS} failed"})
        latest = max((_parse(item["time"]) for item in snapshots), default=None)
        status["latest_snapshot_at"] = latest.isoformat() if latest else None
        status["status"] = "alert" if status["alerts"] else "ok"
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        status.update(status="failed", error=str(detail)[-500:])
        status["alerts"].append({"kind": "maintenance-failed", "message": str(detail)[-300:]})
    status["snapshot_count"] = snapshot_count
    status["finished_at"] = datetime.now(UTC).isoformat()
    try:
        status["repo_bytes"] = sum(path.stat().st_size for path in Path(REPO).rglob("*") if path.is_file())
    except OSError:
        pass
    _save(status)
    print(json.dumps({key: status.get(key) for key in ("status", "plan", "breaker", "forget", "check", "alerts")}))
    return 0 if status["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
