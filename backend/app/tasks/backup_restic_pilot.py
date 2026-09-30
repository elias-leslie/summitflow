"""Opt-in daily Restic coverage with conservative physical-host byte evidence.

The existing hourly scheduler owns this synchronous envelope. Native schedules
are independent. The private journal survives interruption; maintenance_runs
contains its start, source checkpoints and terminal outcome. This is evidence
for scheduled operations, not automatic WAN attribution or cutover approval.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from ipaddress import IPv6Address
from itertools import pairwise
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any

from ..config import settings
from ..logging_config import get_logger
from ..services.backup_keys import backup_key_directory
from ..storage import backups as backup_store
from ..storage import maintenance_runs as maintenance_store
from .backup_executor import create_backup, sync_backup_offsite
from .backup_repository_runtime import (
    _load_json,
    _private_directory,
    _save_json,
    maintain_repository,
    repository_maintenance_failed,
)
from .backup_utils import storage_config_env

WORKFLOW = "restic_daily_pilot"
logger = get_logger(__name__)
SAMPLE_SECONDS = 5
_IDENTITY = ("boot_id", "interface", "ifindex", "iflink", "address", "device", "route_sha256")


def pilot_backend_id() -> str | None:
    """Reserve the explicitly selected backend from hourly maintenance."""
    if not settings.backup_restic_pilot_enabled:
        return None
    return settings.backup_restic_pilot_backend_id.strip() or None


def pilot_reserves_backend(backend_id: str) -> bool:
    """Missing pilot selection fails closed instead of escaping measurement."""
    return settings.backup_restic_pilot_enabled and (not pilot_backend_id() or backend_id == pilot_backend_id())


def _route_fingerprint(routes: str, ipv6: str) -> str:
    """Hash routing topology, not usage counters or container link-local paths."""
    topology: list[tuple[str, ...]] = []
    for line in routes.splitlines()[1:]:
        fields = line.split()
        if len(fields) != 11:
            raise ValueError("IPv4 route evidence is malformed")
        # RefCnt and Use vary with ordinary traffic, not routing topology.
        topology.append(("ipv4", *fields[:4], *fields[6:]))
    for line in ipv6.splitlines():
        fields = line.split()
        if len(fields) != 10:
            raise ValueError("IPv6 route evidence is malformed")
        if int(fields[1], 16) >= 10 and IPv6Address(int(fields[0], 16)).is_link_local:
            # Starting an isolated restore container adds a veth fe80:: route.
            # It cannot redirect public Drive traffic away from the uplink.
            continue
        topology.append(("ipv6", *fields[:6], *fields[8:]))
    return hashlib.sha256(repr(sorted(topology)).encode()).hexdigest()


def sample_interface(interface: str) -> dict[str, Any]:
    """Read physical RX+TX; never replace unreadable/missing counters with zero."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,15}", interface):
        raise ValueError("Pilot physical interface name is invalid")
    root = Path("/sys/class/net") / interface
    if not (root / "device").exists():
        raise ValueError("Pilot requires an available physical host interface")
    routes = Path("/proc/net/route").read_text()
    default_interfaces = {
        fields[0] for line in routes.splitlines()[1:]
        if len(fields := line.split()) >= 4 and fields[1] == "00000000" and int(fields[3], 16) & 1
    }
    if default_interfaces != {interface}:
        raise ValueError("Pilot physical interface must be the sole IPv4 default route")
    ipv6 = Path("/proc/net/ipv6_route").read_text()
    # An alternate IPv6 internet route would escape this physical boundary.
    for line in ipv6.splitlines():
        fields = line.split()
        if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00" and fields[-1] not in {interface, "lo"}:
            raise ValueError("IPv6 default route escapes the pilot physical interface")
    result: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(), "monotonic_ns": time.monotonic_ns(),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "interface": interface, "device": str((root / "device").resolve()),
        "route_sha256": _route_fingerprint(routes, ipv6),
    }
    for field in ("ifindex", "iflink", "address"):
        result[field] = (root / field).read_text().strip()
    for direction in ("rx", "tx"):
        value = int((root / "statistics" / f"{direction}_bytes").read_text())
        if value < 0:
            raise ValueError("Pilot interface counter is negative")
        result[f"{direction}_bytes"] = value
    if not result["boot_id"]:
        raise ValueError("Pilot host boot identity is unavailable")
    return result


def measure_samples(samples: list[dict[str, Any]], errors: list[str]) -> dict[str, Any]:
    """Only comparable, increasing raw intervals yield a byte total."""
    failures = list(errors)
    if len(samples) < 2:
        failures.append("measurement-start-or-end-missing")
    for sample in samples:
        if any(not isinstance(sample.get(key), int) or sample[key] < 0 for key in ("rx_bytes", "tx_bytes")):
            failures.append("invalid-measurement-counter")
    for previous, current in pairwise(samples):
        try:
            if any(previous[key] != current[key] for key in _IDENTITY):
                failures.append("boot-interface-or-route-changed")
            first = datetime.fromisoformat(previous["timestamp"])
            last = datetime.fromisoformat(current["timestamp"])
            if first.tzinfo is None or last.tzinfo is None or last <= first or current["monotonic_ns"] <= previous["monotonic_ns"]:
                failures.append("invalid-measurement-interval")
            if any(current[key] < previous[key] for key in ("rx_bytes", "tx_bytes")):
                failures.append("physical-counter-reset")
        except (KeyError, TypeError, ValueError):
            failures.append("invalid-measurement-sample")
    result: dict[str, Any] = {
        "valid": not failures, "errors": sorted(set(failures)), "samples": samples,
        "sample_interval_seconds": SAMPLE_SECONDS,
        "scope": "scheduled-pilot-envelope", "attribution": "conservative-HOST-upper-bound",
        "includes_unrelated_and_lan_traffic": True, "exact_backup_wan_attribution": False,
        "outside_operations_require_separate_audit": True,
    }
    if not failures:
        result.update(
            rx_bytes=samples[-1]["rx_bytes"] - samples[0]["rx_bytes"],
            tx_bytes=samples[-1]["tx_bytes"] - samples[0]["tx_bytes"],
        )
        result["total_bytes"] = result["rx_bytes"] + result["tx_bytes"]
    return result


def _pilot_environment(backend_id: str) -> dict[str, str]:
    backend = backup_store.get_backend(backend_id)
    if not backend or not backend.get("enabled") or backend.get("is_default"):
        raise ValueError("Pilot requires an enabled explicit nondefault backend")
    config = backend.get("config") or {}
    if config.get("engine") != "restic" or not config.get("restic_remote_repository"):
        raise ValueError("Pilot requires a Restic backend with an independent offsite repository")
    return storage_config_env({**config, "__backend_type": backend["backend_type"], "__backend_id": backend_id})


def _verified_outcome(source: dict[str, Any], backend_id: str, on_progress: Callable[[], None] | None, *, seed: bool) -> dict[str, Any]:
    source_id = str(source["id"])
    result = create_backup(
        project_id=str(source.get("project_id") or source_id), source_id=source_id,
        storage_backend_id=backend_id, backup_type="scheduled",
        note="Daily seed Restic pilot" if seed else "Daily post-seed Restic pilot", retention_days=source.get("retention_days"),
        on_progress=on_progress,
    )
    backup_id = result.get("backup_id")
    row = backup_store.get_backup(str(backup_id)) if backup_id else None
    verification = (row or {}).get("verification_json") or {}
    attempts: list[dict[str, Any]] = [{"operation": "capture-and-copy", "status": result.get("status"), "offsite_status": (verification.get("offsite") or {}).get("status")}]
    # Existing retry is synchronous, owns the normal source lease and persists
    # SQL verification. A remaining pending result is terminal failure here,
    # not background work allowed to escape the measured envelope.
    if row and result.get("status") in {"completed", "completed_pending_upload"} and (verification.get("offsite") or {}).get("status") != "verified":
        attempts.append({"operation": "offsite-retry", "status": "running"})
        try:
            sync_backup_offsite(str(backup_id), on_progress=on_progress)
            row = backup_store.get_backup(str(backup_id))
            verification = (row or {}).get("verification_json") or {}
            attempts[-1]["status"] = (verification.get("offsite") or {}).get("status")
        except Exception as exc:
            attempts[-1].update(status="failed", error=str(exc))
    verified = bool(
        row and row.get("source_id") == source_id and row.get("storage_backend_id") == backend_id
        and row.get("status") == "completed" and row.get("verified") is True
        and verification.get("format") == "restic-v1"
        and (verification.get("offsite") or {}).get("status") == "verified"
        and verification.get("remote_snapshot_id") and verification.get("remote_repository_id")
        and not result.get("offsite_error")
    )
    return {
        "source_id": source_id, "backup_id": backup_id, "status": "verified" if verified else "failed",
        "attempts": attempts, "offsite": verification.get("offsite"),
        "had_failed_attempt": any(attempt.get("status") in {"failed", "error", "pending", "completed_pending_upload"} or (attempt.get("operation") == "capture-and-copy" and attempt.get("offsite_status") != "verified") for attempt in attempts),
        "remote_snapshot_id": verification.get("remote_snapshot_id"),
        "error": result.get("error") or (None if verified else "Daily source offsite verification incomplete"),
    }


def _execute_day(path: Path, state: dict[str, Any], *, backend_id: str, now: datetime, on_progress: Callable[[], None] | None) -> dict[str, Any]:
    env = _pilot_environment(backend_id)
    sources = [source for source in backup_store.list_sources() if source.get("enabled")]
    required = sorted(str(source["id"]) for source in sources)
    missing_seed: list[str] = []
    for source_id in required:
        rows, _ = backup_store.list_backups(source_id=source_id, limit=100)
        if not any(
            row.get("source_id") == source_id and row.get("storage_backend_id") == backend_id
            and row.get("status") == "completed" and row.get("verified") is True
            and (verification := row.get("verification_json") or {}).get("format") == "restic-v1"
            and (verification.get("offsite") or {}).get("status") == "verified"
            and verification.get("remote_snapshot_id") and verification.get("remote_repository_id")
            for row in rows
        ):
            missing_seed.append(source_id)
    started_at = datetime.now(UTC)
    run: dict[str, Any] = {
        "day_utc": now.date().isoformat(), "backend_id": backend_id,
        "started_at": started_at.isoformat(), "status": "running", "phase": "start",
        "seed": bool(missing_seed), "missing_seed_sources": missing_seed,
        "required_sources": required, "outcomes": [],
        "samples": [], "sample_checkpoints": [], "sample_count": 0,
        "measurement_errors": [], "coverage_verified": False,
        "cutover_qualified": False, "outside_operations_audited": False,
    }
    state["last_run"] = run
    guard = RLock()

    def checkpoint() -> None:
        with guard:
            _save_json(path, state)
            try:
                maintenance_store.record_maintenance_run(
                    WORKFLOW, run["status"], started_at=started_at,
                    summary={**run, "measurement": measure_samples(run["samples"], run["measurement_errors"])},
                )
            except Exception as exc:
                # A final SQL failure must not leave a private success that the
                # next hourly pass could adopt as a qualified daily result.
                run.update(status="failed", checkpoint_error=str(exc))
                _save_json(path, state)
                raise

    def sample(*, boundary: bool = False) -> None:
        with guard:
            try:
                current = sample_interface(settings.backup_restic_pilot_interface)
                if run["samples"]:
                    continuity = measure_samples([run["samples"][-1], current], [])
                    run["measurement_errors"] = sorted(set(run["measurement_errors"] + continuity["errors"]))
                run["sample_count"] += 1
                run["samples"] = [run["samples"][0], current] if run["samples"] else [current]
                if boundary:
                    run["sample_checkpoints"].append({"phase": run["phase"], **current})
            except Exception as exc:
                run["measurement_errors"].append(str(exc))
            _save_json(path, state)

    stopped = Event()

    def monitor() -> None:
        while not stopped.wait(SAMPLE_SECONDS):
            try:
                sample()
            except Exception as exc:
                with guard:
                    run["measurement_errors"].append(f"Counter checkpoint failed: {exc}")
                return

    thread = Thread(target=monitor, name="restic-pilot-counters", daemon=True)
    sample(boundary=True)
    checkpoint()
    if run["measurement_errors"]:
        run.update(status="failed", phase="measurement-unavailable", measurement=measure_samples(run["samples"], run["measurement_errors"]), finished_at=datetime.now(UTC).isoformat())
        checkpoint()
        return run
    thread.start()
    try:
        for source in sources:
            with guard:
                run["phase"] = f"source:{source['id']}"
            checkpoint()
            try:
                outcome = _verified_outcome(source, backend_id, on_progress, seed=run["seed"])
            except Exception as exc:
                outcome = {"source_id": str(source["id"]), "status": "failed", "error": str(exc)}
            with guard:
                run["outcomes"].append(outcome)
            sample(boundary=True)
            checkpoint()
        with guard:
            run["phase"] = "maintenance"
        checkpoint()
        try:
            # Reuse the existing separately authorized prune qualification;
            # this schedule never sets or promotes it.
            maintenance = maintain_repository(env, dry_run=env.get("RESTIC_OFFSITE_PRUNE_QUALIFIED") != "true")
        except Exception as exc:
            maintenance = {"status": "failed", "error": str(exc)}
        with guard:
            run["maintenance"] = maintenance
        current = sorted(str(source["id"]) for source in backup_store.list_sources() if source.get("enabled"))
        with guard:
            run["sources_changed"] = current != required
            run["coverage_verified"] = bool(required) and not run["sources_changed"] and all(outcome["status"] == "verified" for outcome in run["outcomes"])
    finally:
        stopped.set()
        thread.join()
        sample(boundary=True)
        finished_at = datetime.now(UTC)
        run["finished_at"] = finished_at.isoformat()
        run["crossed_utc_date"] = finished_at.date() != now.date()
        if run["crossed_utc_date"]:
            run["coverage_verified"] = False
        run["measurement"] = measure_samples(run["samples"], run["measurement_errors"])
        run["status"] = "completed" if run["coverage_verified"] and run["measurement"]["valid"] and not repository_maintenance_failed(run.get("maintenance")) else "failed"
        run["phase"] = "finished"
        checkpoint()
    return run


def run_daily_restic_pilot(*, on_progress: Callable[[], None] | None = None) -> dict[str, Any]:
    """Run each UTC day once; interrupted/manual/retry days cannot pass coverage."""
    if not settings.backup_restic_pilot_enabled:
        return {"status": "skipped", "reason": "pilot-disabled"}
    started_at = datetime.now(UTC)
    try:
        backend_id = pilot_backend_id()
        if not backend_id:
            raise ValueError("Pilot requires an explicit backend ID")
        daily = settings.backup_restic_pilot_daily_utc
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", daily):
            raise ValueError("Pilot daily UTC time must be HH:MM")
        directory = backup_key_directory() / "restic-state"
        _private_directory(directory)
        descriptor = os.open(directory / ".pilot.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"status": "skipped", "reason": "pilot-active"}
            path = directory / "pilot.json"
            state = _load_json(path)
            previous = state.get("last_run") or {}
            if previous.get("status") == "running":
                previous.update(status="incomplete", phase="interrupted", coverage_verified=False, cutover_qualified=False)
                previous.setdefault("measurement_errors", []).append("interrupted-process-restart")
                previous["measurement"] = measure_samples(previous.get("samples", []), previous["measurement_errors"])
                _save_json(path, state)
                maintenance_store.record_maintenance_run(WORKFLOW, "incomplete", started_at=datetime.fromisoformat(previous["started_at"]), summary=previous, error_message="Interrupted measured window; automatic retry cannot qualify this day")
            if previous.get("day_utc", "") >= started_at.date().isoformat():
                return {"status": "skipped", "reason": "daily-attempt-already-recorded", "daily_status": previous.get("status")}
            if started_at.strftime("%H:%M") < daily:
                return {"status": "skipped", "reason": "before-daily-utc-time"}
            return _execute_day(path, state, backend_id=backend_id, now=started_at, on_progress=on_progress)
        finally:
            os.close(descriptor)
    except Exception as exc:
        result = {"status": "failed", "error": str(exc), "coverage_verified": False, "cutover_qualified": False}
        try:
            maintenance_store.record_maintenance_run(WORKFLOW, "failed", started_at=started_at, summary=result, error_message=str(exc))
        except Exception:
            logger.exception("restic_pilot_failure_history_unavailable")
            result["history_error"] = "Maintenance history unavailable; inspect private pilot checkpoint"
        return result
