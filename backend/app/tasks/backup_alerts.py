"""Backup health: a real missing recovery point raises one alert with the real error, cleared on recovery.

Real means a recovery point that is actually missing: no good local btrbk point for over a day, no good Google
Drive snapshot for 48 hours after the job's own retries, a failing Drive data check or test restore, a Proxmox
target without a fresh copy. A slow or retried run is not an alert.

Each alert lives in the notifications table: a ``failed`` notification while the condition holds and an ``info``
recovery notification when it clears. The latest notification per alert key is the alert state, so a worker
restart or a dismissed notification never re-sends the same alert every hour.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.notifications import create_notification, dismiss_notification
from .backup_utils import _FREQUENCY_DELTAS

logger = get_logger(__name__)

SOURCE_STALE_FACTOR = 2  # An external source is overdue with no success in 2x its frequency.
# Active conditions and per-source freshness for Nightshift, next to the PVE receipt.
SOURCES_RECEIPT = Path.home() / ".local/state/summitflow/backup-freshness/sources.json"


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def external_statuses(now: datetime) -> dict[str, dict[str, Any]]:
    """Backups other projects run (Blackbox archive pull, Portfolio-AI artifacts), with the same freshness window."""
    from .backup_external import list_external_sources, probe

    out: dict[str, dict[str, Any]] = {}
    try:
        sources = list_external_sources()
    except Exception:  # a missing table or database hiccup never breaks the alert pass
        logger.exception("external_backup_sources_unreadable")
        return out
    for source in sources:
        if not source.get("enabled"):
            continue
        frequency = str(source.get("frequency") or "daily")
        window = _FREQUENCY_DELTAS.get(frequency, timedelta(days=1)) * SOURCE_STALE_FACTOR
        seen = probe(source)
        last_success = _parse(seen["last_success_at"])
        ok = bool(last_success and now - last_success <= window) or seen["last_status"] == "running"
        error = seen["last_error"] or (None if ok else "no success within the freshness window")
        out[str(source["id"])] = {"ok": ok, "frequency": frequency, "stale_after_hours": round(window.total_seconds() / 3600, 1),
                                  "last_success_at": last_success.isoformat() if last_success else None,
                                  "last_status": seen["last_status"], "offline_since": None,
                                  "last_error": str(error)[:500] if error else None,
                                  "external": True, "name": source.get("name"), "owner_project": source.get("owner_project"),
                                  "kind": source.get("kind"), "target": source.get("target")}
    return out


def _external_conditions(statuses: Mapping[str, Mapping[str, Any]], now: datetime) -> dict[str, dict[str, str]]:
    stale = sorted(source_id for source_id, status in statuses.items() if status.get("external") and not status["ok"])
    if not stale:
        return {}
    details = []
    for source_id in stale:
        last_success = _parse(statuses[source_id]["last_success_at"])
        age = f"{(now - last_success).total_seconds() / 3600:.0f}h ago" if last_success else "never"
        details.append(f"{source_id} (last success {age}; {str(statuses[source_id]['last_error'])[:200]})")
    return {"sources-stale": {
        "title": "Backups are overdue",
        "message": f"No successful backup within twice the schedule for: {'; '.join(details)}",
        "reason": "sources-stale:" + ",".join(stale),
    }}


def _proxmox_conditions(now: datetime) -> dict[str, dict[str, str]]:
    from .backup_proxmox import write_freshness_receipt

    receipt = write_freshness_receipt(now)
    behind = [item for item in receipt["targets"] if not item["fresh"]]
    if not behind:
        return {}
    detail = "; ".join(f"{item['target']} ({item['status']}{', ' + str(item['age_hours']) + 'h old' if item.get('age_hours') is not None else ''}{', ' + item['reason'] if item.get('reason') else ''})" for item in behind)
    return {"proxmox-freshness": {
        "title": "Proxmox backups are not current",
        "message": f"Each covered guest and the cluster config needs a Google Drive copy newer than {receipt['max_age_hours']}h: {detail}",
        "reason": "proxmox:" + ",".join(sorted(f"{item['target']}={item['status']}" for item in behind)),
    }}


def _overview_conditions(now: datetime) -> dict[str, dict[str, str]]:
    from .backup_overview import health_problems

    return {f"backup:{problem['key']}": {"title": problem["title"], "message": problem["message"], "reason": problem["key"]}
            for problem in health_problems(now)}


def _fingerprint(key: str, reason: str) -> str:
    return hashlib.sha256(json.dumps([key, reason]).encode()).hexdigest()[:16]


def _write_sources_receipt(now: datetime, conditions: Mapping[str, Mapping[str, str]], statuses: Mapping[str, Mapping[str, Any]]) -> None:
    """Atomically publish the active alert conditions for Nightshift; never fails the alert pass.

    ``sources`` holds the local btrbk layer (``host-btrbk``), the daily Google Drive job (``offsite-restic``),
    each Proxmox/off-disk job, and the external backups other projects run. ``offsite_runs`` gives the Drive job's
    remote and its latest run window, so a bandwidth alert on rclone can be matched to a backup. Nothing is
    ever refused for disk space any more, so ``capture_refused`` stays false.
    """
    try:
        from .backup_offsite import read_state
        from .backup_overview import offsite_runs

        receipt = {
            "schema_version": 1, "generated_at": now.isoformat(), "ok": not conditions,
            "capture_refused": False, "capture_refused_since": None,
            "conditions": [{"key": key, "title": condition["title"], "reason": condition["reason"], "message": condition["message"][:1000]}
                           for key, condition in sorted(conditions.items())],
            "sources": dict(sorted(statuses.items())),
            "offsite_runs": offsite_runs(read_state()),
        }
        SOURCES_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        temporary = SOURCES_RECEIPT.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, indent=1, default=str) + "\n")
        os.replace(temporary, SOURCES_RECEIPT)
    except Exception:
        logger.exception("backup_sources_receipt_failed")


def evaluate_backup_alerts(summary: Mapping[str, Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Raise or clear backup alerts and refresh the freshness receipts; run after each backup run and by the worker's hourly tick."""
    current = now or datetime.now(UTC)
    conditions: dict[str, dict[str, str]] = {}
    statuses: dict[str, dict[str, Any]] = {}

    def sources() -> dict[str, dict[str, str]]:
        from .backup_overview import freshness_sources

        statuses.update(freshness_sources(current))
        statuses.update(external_statuses(current))
        return _external_conditions(statuses, current)

    for name, collect in (
        ("backup", lambda: _overview_conditions(current)),
        ("sources", sources),
        ("proxmox", lambda: _proxmox_conditions(current)),
    ):
        try:
            conditions.update(collect())
        except Exception as exc:
            logger.exception("backup_alert_evaluation_failed", check=name)
            conditions[f"evaluation:{name}"] = {"title": "Backup health check failed", "message": f"The {name} backup health check failed: {exc}", "reason": "evaluation-failed"}
    latest = backup_store.latest_backup_alerts()
    raised: list[str] = []
    cleared: list[str] = []
    for key, condition in conditions.items():
        fingerprint = _fingerprint(key, condition["reason"])
        previous = latest.get(key) or {}
        if previous.get("event") == "failed" and previous.get("fingerprint") == fingerprint:
            continue  # Already alerted for this exact condition.
        if previous.get("event") == "failed" and previous.get("status") != "dismissed":
            dismiss_notification(str(previous["id"]))
        create_notification(
            project_id="summitflow", notification_type="system", title=condition["title"],
            message=condition["message"][:2000], severity="error",
            metadata={"backup_alert": key, "backup_alert_event": "failed", "backup_alert_fingerprint": fingerprint},
            dedupe_key=f"backup-alert:{key}:{fingerprint}:{current.isoformat()}",
        )
        raised.append(key)
    for key, previous in latest.items():
        if key in conditions or previous.get("event") != "failed":
            continue
        if previous.get("status") != "dismissed":
            dismiss_notification(str(previous["id"]))
        create_notification(
            project_id="summitflow", notification_type="system", title=f"Recovered: {previous.get('title')}",
            message="The condition behind this backup alert has cleared.", severity="info",
            metadata={"backup_alert": key, "backup_alert_event": "recovered", "backup_alert_fingerprint": previous.get("fingerprint")},
            dedupe_key=f"backup-alert:{key}:recovered:{current.isoformat()}",
        )
        cleared.append(key)
    active = sorted(conditions)
    _write_sources_receipt(current, conditions, statuses)
    if raised or cleared:
        logger.warning("backup_alerts_changed", raised=raised, cleared=cleared, active=active)
    return {"active": active, "raised": raised, "cleared": cleared}
