"""Persistent backup failures raise one alert with the real error, cleared on recovery.

Each alert lives in the notifications table: a ``failed`` notification while
the condition holds and an ``info`` recovery notification when it clears. The
latest notification per alert key is the alert state, so a worker restart or
a dismissed notification never re-sends the same alert every hour.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.notifications import create_notification, dismiss_notification
from ..utils.host_retention_policy import HostRetentionPolicy
from ..utils.transient_scratch import SCRATCH_ROOT
from .backup_utils import _FREQUENCY_DELTAS

logger = get_logger(__name__)

PENDING_COPY_ALERT_HOURS = 6
PRUNE_FAILURE_ALERT_RUNS = 2  # Alert once prune has failed more than this many runs.
PRUNE_OVERDUE_DAYS = 14  # Twice the weekly prune cadence.
SOURCE_STALE_FACTOR = 2  # Alert when a source has no success in 2x its frequency.
_CAPACITY_ERROR = "insufficient host-policy headroom"
OFFLINE_MARKER_SECONDS = 3 * 3600  # Offline sources are retried every tick, refreshing this.


def _offline_key(source_id: str) -> str:
    return f"backup:source-offline:{source_id}"


def mark_source_offline(source_id: str) -> None:
    """Remember that the owner powered the source's guest off, so it is not reported stale."""
    from ..services.redis_pool import get_redis

    try:
        get_redis().set(_offline_key(source_id), datetime.now(UTC).isoformat(), ex=OFFLINE_MARKER_SECONDS)
    except Exception:
        logger.warning("backup_offline_marker_failed", source_id=source_id)


def source_offline_since(source_id: str) -> str | None:
    from ..services.redis_pool import get_redis

    try:
        value = get_redis().get(_offline_key(source_id))
    except Exception:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return value if isinstance(value, str) else None


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


def _restic_backends() -> list[tuple[str, dict[str, str]]]:
    from .backup_utils import storage_config_env

    backends = []
    for backend in backup_store.list_backends(enabled_only=True):
        config = backend.get("config") or {}
        if not isinstance(config, Mapping) or config.get("engine") != "restic" or config.get("restic_automatic_maintenance") is False:
            continue
        env = storage_config_env({**config, "__backend_type": backend["backend_type"], "__backend_id": backend["id"]})
        backends.append((str(backend["id"]), env))
    return backends


def _repository_conditions(now: datetime, copies: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    from .backup_repository_runtime import repository_journal

    conditions: dict[str, dict[str, str]] = {}
    for backend_id, env in _restic_backends():
        try:
            state = repository_journal(env)
        except Exception as exc:
            conditions[f"journal:{backend_id}"] = {
                "title": "Backup repository state unreadable",
                "message": f"The repository journal for {backend_id} could not be read: {exc}",
                "reason": "journal-unreadable",
            }
            continue
        offsite = state.get("offsite") or {}
        pending = list(offsite.get("pending_snapshot_ids") or [])
        if pending and env.get("RESTIC_REMOTE_REPOSITORY"):
            completed = {item.get("snapshot_id"): _parse(item.get("completed_at")) for item in (state.get("sources") or {}).values()}
            known = [time for snapshot_id in pending if (time := completed.get(snapshot_id))]
            # A pending snapshot no longer in the per-source checkpoint is older
            # than every known one; the last verified copy bounds it instead.
            waiting_since = min(known) if known and len(known) == len(pending) else (_parse(offsite.get("verified_at")) or min(known, default=None))
            if waiting_since and now - waiting_since > timedelta(hours=PENDING_COPY_ALERT_HOURS):
                run_error = next((value.get("error") or value.get("reason") for value in copies.values() if isinstance(value, Mapping) and (value.get("error") or value.get("reason"))), None)
                last = offsite.get("last_copy_error") or {}
                error = run_error or last.get("error") or offsite.get("error") or "no copy error was recorded; the copy has not completed"
                hours = (now - waiting_since).total_seconds() / 3600
                conditions[f"offsite-copy:{backend_id}"] = {
                    "title": "Offsite backup copy is behind",
                    "message": f"{len(pending)} snapshots have waited {hours:.0f}h for the offsite copy (alert after {PENDING_COPY_ALERT_HOURS}h). Last error: {error}",
                    "reason": "offsite-copy-pending",
                }
        maintenance = state.get("maintenance") or {}
        result = maintenance.get("result") or {}
        for label in ("local", "remote") if env.get("RESTIC_REMOTE_REPOSITORY") else ("local",):
            previous = maintenance.get(label) or {}
            prune = (result.get(label) or {}).get("prune") or {}
            failures = int(previous.get("prune_failures") or 0)
            pruned_at = _parse(previous.get("pruned_at"))
            if failures > PRUNE_FAILURE_ALERT_RUNS:
                conditions[f"prune:{backend_id}:{label}"] = {
                    "title": f"{label.capitalize()} backup prune keeps failing",
                    "message": f"The {label} repository prune failed {failures} runs in a row. Last error: {prune.get('error') or prune.get('reason') or 'unknown'}",
                    "reason": "prune-failing",
                }
            elif maintenance.get("last_run_at") and (pruned_at is None or now - pruned_at > timedelta(days=PRUNE_OVERDUE_DAYS)):
                since = f"since {pruned_at.date().isoformat()}" if pruned_at else "ever"
                conditions[f"prune:{backend_id}:{label}"] = {
                    "title": f"{label.capitalize()} backup prune is overdue",
                    "message": f"The {label} repository has not been pruned {since}, so its space is not reclaimed. Latest reason: {prune.get('error') or prune.get('reason') or prune.get('status') or 'unknown'}",
                    "reason": "prune-overdue",
                }
    return conditions


def _source_conditions(now: datetime) -> dict[str, dict[str, str]]:
    stale: list[str] = []
    details: list[str] = []
    sources = {str(source["id"]): source for source in backup_store.list_sources()}
    for row in backup_store.get_backup_health_summary():
        source = sources.get(str(row["source_id"])) or {}
        if not row.get("enabled") or not source:
            continue
        window = _FREQUENCY_DELTAS.get(str(source.get("frequency") or "daily"), timedelta(days=1)) * SOURCE_STALE_FACTOR
        last_success = _parse(row.get("last_success_at"))
        created = _parse(source.get("created_at"))
        if last_success and now - last_success <= window:
            continue
        if last_success is None and created and now - created <= window:
            continue
        if source_offline_since(str(row["source_id"])):
            continue  # The owner powered the guest off; it resumes when the guest runs.
        rows, _ = backup_store.list_backups(source_id=str(row["source_id"]), limit=1)
        latest = rows[0] if rows else {}
        error = latest.get("error_message") or (f"latest attempt {latest.get('status')}" if latest else "no attempt recorded")
        age = f"{(now - last_success).total_seconds() / 3600:.0f}h ago" if last_success else "never"
        stale.append(str(row["source_id"]))
        details.append(f"{row['source_id']} (last success {age}; {str(error)[:200]})")
    if not stale:
        return {}
    return {"sources-stale": {
        "title": "Backups are overdue",
        "message": f"No successful backup within twice the schedule for: {'; '.join(details)}",
        "reason": "sources-stale:" + ",".join(sorted(stale)),
    }}


def _capacity_conditions(summary: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    from .backup_restic import ResticConfig

    refused = [str(item.get("source_id")) for item in summary.get("results") or [] if _CAPACITY_ERROR in str(item.get("error") or "")]
    reserve = int(HostRetentionPolicy.from_env().pressure_min_free_gb * 1024**3)
    low: list[str] = []
    paths = [SCRATCH_ROOT]
    for _, env in _restic_backends():
        try:
            paths.append(ResticConfig.from_env(env).local_repository)
        except Exception:
            continue
    seen: set[int] = set()
    for path in paths:
        while not path.exists() and path != path.parent:
            path = path.parent
        try:
            device = path.stat().st_dev
            if device in seen:
                continue
            seen.add(device)
            free = shutil.disk_usage(path).free
        except OSError:
            continue
        if free < reserve:
            low.append(f"{path} has {free / 1024**3:.1f} GB free")
    if not refused and not low:
        return {}
    parts = []
    if refused:
        parts.append(f"capture refused for {', '.join(sorted(refused))}")
    if low:
        parts.append("; ".join(low))
    return {"capacity": {
        "title": "Backup capture stopped: low disk space",
        "message": f"Backups keep {reserve / 1024**3:.0f} GB free and stop capturing below that: {'; '.join(parts)}. Free space, then the next run resumes.",
        "reason": "capacity",
    }}


def _proxmox_conditions(now: datetime) -> dict[str, dict[str, str]]:
    from .backup_proxmox import write_freshness_receipt

    receipt = write_freshness_receipt(now)
    behind = [item for item in receipt["targets"] if not item["fresh"]]
    if not behind:
        return {}
    detail = "; ".join(f"{item['target']} ({item['status']}{', ' + str(item['age_hours']) + 'h old' if item.get('age_hours') is not None else ''})" for item in behind)
    return {"proxmox-freshness": {
        "title": "Proxmox backups are not current",
        "message": f"Each covered guest and the cluster config needs an offsite-verified backup newer than {receipt['max_age_hours']}h: {detail}",
        "reason": "proxmox:" + ",".join(sorted(f"{item['target']}={item['status']}" for item in behind)),
    }}


def _fingerprint(key: str, reason: str) -> str:
    return hashlib.sha256(json.dumps([key, reason]).encode()).hexdigest()[:16]


def evaluate_backup_alerts(summary: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Raise or clear persistent-failure alerts after each scheduler run."""
    current = now or datetime.now(UTC)
    conditions: dict[str, dict[str, str]] = {}
    for name, collect in (
        ("repository", lambda: _repository_conditions(current, summary.get("repository_copy") or {})),
        ("sources", lambda: _source_conditions(current)),
        ("capacity", lambda: _capacity_conditions(summary)),
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
    if raised or cleared:
        logger.warning("backup_alerts_changed", raised=raised, cleared=cleared, active=active)
    return {"active": active, "raised": raised, "cleared": cleared}
