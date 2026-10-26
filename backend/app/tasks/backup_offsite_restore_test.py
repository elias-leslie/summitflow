"""Monthly offsite restore test that proves a real restore and sets restore_verified.

Each run restores the latest offsite-verified point of rotating sources from the
Drive repository into private restore scratch: one small file source and one
project database source. A sampled set of restored files is compared by SHA-256
against the same files restored from the independent local repository, and a
database dump is loaded into a disposable PostgreSQL container whose per-table
row counts must match the dump's own COPY counts. A project with Git is rebuilt
from its restored bundle into scratch, and HEAD and its commit count must match
the capture. Results are recorded as drill
evidence on the source and as ``isolated_restore`` on the backup. Infrastructure
and critical configuration restores stay with the weekly critical restore.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.notifications import create_notification
from ..utils import nightshift_stack
from ..utils.transient_scratch import ensure_scratch_capacity, restore_scratch, tree_bytes
from .backup_activity import BackupCancelled, run_bulk_process
from .backup_native_recovery import drill_git_history

logger = get_logger(__name__)

MONTHLY_CADENCE_DAYS = 28
RESTORE_VERIFIED_DAYS = 35  # One monthly cadence plus a missed weekly tick.
MAX_RESTORE_BYTES = 1024**3  # Small sources only; large trees stay on integrity readback.
SAMPLE_FILES = 16
SAMPLE_MAX_FILE_BYTES = 64 * 1024**2
POSTGRES_IMAGE = "pgvector/pgvector:pg16"
POSTGRES_READY_SECONDS = 120
DATABASE_LOAD_TIMEOUT = 1800
METHOD = "monthly-offsite-restore"
RECEIPT = Path.home() / ".local/state/summitflow/backup-restore-test/monthly.json"
_EXCLUDED_SOURCES = {"infrastructure"}  # Covered by the weekly critical offsite restore.
_ROLE_PATTERNS = (
    re.compile(r"\bOWNER TO (\"[^\"]+\"|[A-Za-z_][\w$-]*)"),
    re.compile(r"(?:^|\s)(?:GRANT|REVOKE) .* (?:TO|FROM) (.+?)(?: WITH GRANT OPTION)?;$"),
    re.compile(r"^CREATE POLICY .* TO (.+?)(?: USING| WITH CHECK|;)"),
    re.compile(r"\bFOR ROLE (\"[^\"]+\"|[A-Za-z_][\w$-]*)"),
)
_IDENTIFIER = r'("(?:[^"]|"")*"|[^\s."]+)'
_COPY_TABLE = re.compile(rf"^COPY {_IDENTIFIER}\.{_IDENTIFIER} ")
_BUILTIN_ROLES = {"public", "postgres", "current_user", "session_user", "current_role"}


def restore_verified(source: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """A source's recovery path is verified by a recent passing real restore."""
    at = source.get("last_drill_at")
    if source.get("last_drill_ok") is not True or not at:
        return False
    when = at if isinstance(at, datetime) else datetime.fromisoformat(str(at))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - when <= timedelta(days=RESTORE_VERIFIED_DAYS)


def _offsite_point(source_id: str) -> dict[str, Any] | None:
    from .backup_repository_runtime import is_repository_backup

    rows, _ = backup_store.list_backups(source_id=source_id, limit=20)
    for row in sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True):
        verification = row.get("verification_json") or {}
        if row.get("status") != "completed" or not is_repository_backup(row):
            continue
        if str((verification.get("capture") or {}).get("kind", "")).startswith("proxmox-"):
            continue  # Guest streams are read back by their own stream verification.
        if (verification.get("offsite") or {}).get("status") != "verified":
            continue
        if verification.get("snapshot_id") and verification.get("remote_snapshot_id"):
            return row
    return None


def select_rotation(sources: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Least recently drilled eligible file source and database source."""
    from .backup_proxmox import is_proxmox_path
    from .backup_repository_runtime import _known_restore_bytes

    eligible: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for source in sources:
        if not source.get("enabled") or source["id"] in _EXCLUDED_SOURCES or is_proxmox_path(source.get("path")):
            continue
        point = _offsite_point(str(source["id"]))
        if point is not None and 0 < _known_restore_bytes(point) <= MAX_RESTORE_BYTES:
            eligible.append((source, point))
    epoch = datetime.min.replace(tzinfo=UTC)

    def last_drill(item: tuple[dict[str, Any], dict[str, Any]]) -> tuple[datetime, str]:
        value = item[0].get("last_drill_at")
        when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value)) if value else epoch
        return (when if when.tzinfo else when.replace(tzinfo=UTC), str(item[0]["id"]))

    eligible.sort(key=last_drill)
    database = next((item for item in eligible if (item[1].get("verification_json") or {}).get("has_db") is True), None)
    files = next((item for item in eligible if (item[1].get("verification_json") or {}).get("has_db") is not True), None)
    return [item for item in (files, database) if item is not None]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample(root: Path, seed: str) -> list[str]:
    candidates = sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= SAMPLE_MAX_FILE_BYTES
        and not any(char in path.relative_to(root).as_posix() for char in "*?[]\\\n")
    )
    return sorted(random.Random(seed).sample(candidates, min(SAMPLE_FILES, len(candidates))))


def dump_row_counts(dump: Path) -> dict[str, int]:
    """Rows per table as captured, read from a plain pg_dump's COPY blocks."""
    counts: dict[str, int] = {}
    table: str | None = None
    with dump.open("rb") as stream:
        for raw in stream:
            if table is not None:
                if raw.rstrip(b"\r\n") == b"\\.":
                    table = None
                else:
                    counts[table] += 1
            elif raw.startswith(b"COPY ") and raw.rstrip().endswith(b"FROM stdin;"):
                match = _COPY_TABLE.match(raw.decode())
                if match is None:
                    raise RuntimeError("Database dump has an unreadable COPY table name")
                table = ".".join(part[1:-1].replace('""', '"') if part.startswith('"') else part for part in match.groups())
                counts.setdefault(table, 0)
    if table is not None:
        raise RuntimeError("Database dump ends inside a COPY block")
    return counts


def _dump_roles(dump: Path) -> list[str]:
    roles: set[str] = set()
    with dump.open("r", errors="replace") as stream:
        for line in stream:
            if line.startswith("COPY "):
                # Skip table data entirely; only DDL names roles.
                for data in stream:
                    if data.rstrip("\r\n") == "\\.":
                        break
                continue
            for pattern in _ROLE_PATTERNS:
                for match in pattern.findall(line.strip()):
                    for name in match.split(","):
                        name = name.strip().removeprefix("GROUP ").strip().strip('"')
                        if name and name.lower() not in _BUILTIN_ROLES and re.fullmatch(r"[\w$-]+", name):
                            roles.add(name)
    return sorted(roles)


def _docker(arguments: list[str], *, timeout: float = 120, scratch: Path | None = None) -> subprocess.CompletedProcess[Any]:
    return run_bulk_process(
        [*nightshift_stack.docker_cli(), *arguments], phase="restore", object_name="disposable restore database",
        timeout=timeout, capacity_check=(lambda: ensure_scratch_capacity(scratch, 0)) if scratch else None,
    )


def _first_error(stderr: object) -> str:
    return next((line for line in str(stderr or "").splitlines() if "ERROR" in line), "")[:300]


def verify_database_dump(dump: Path, scratch: Path) -> dict[str, Any]:
    """Load a plain project dump into a disposable PostgreSQL and compare row counts."""
    if not nightshift_stack.docker_runtime_available():
        return {"skipped": True, "reason": "unsupported: no container runtime for the disposable restore database"}
    if dump.suffix == ".gz":
        plain = scratch / "database.sql"
        with gzip.open(dump, "rb") as source, plain.open("wb") as target:
            shutil.copyfileobj(source, target, 1024 * 1024)
        dump = plain
    expected = dump_row_counts(dump)
    roles = _dump_roles(dump)
    data = scratch / "postgres"
    data.mkdir(mode=0o700)
    name = f"sf-restore-test-pg-{scratch.name}"
    started = time.monotonic()
    try:
        created = _docker([
            "run", "-d", "--name", name, "--pull", "never", "--network", "none",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "--mount", f"type=bind,source={data},target=/var/lib/postgresql/data",
            "--mount", f"type=bind,source={dump},target=/restore/database.sql,readonly",
            "--tmpfs", "/var/run/postgresql:rw,mode=1777", "--tmpfs", "/tmp:rw,mode=1777",
            "-e", "POSTGRES_PASSWORD=restore_test", POSTGRES_IMAGE, "-c", "listen_addresses=",
        ])
        if created.returncode:
            raise RuntimeError("Disposable PostgreSQL could not start")
        deadline = time.monotonic() + POSTGRES_READY_SECONDS
        while True:
            logs = subprocess.run([*nightshift_stack.docker_cli(), "logs", name], capture_output=True, text=True, timeout=30, check=False)
            if "PostgreSQL init process complete" in logs.stdout + logs.stderr and _docker(["exec", name, "pg_isready", "-U", "postgres"]).returncode == 0:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Disposable PostgreSQL did not become ready")
            time.sleep(1)
        psql = ["exec", name, "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres"]
        # CREATE DATABASE cannot share psql's single -c transaction with roles.
        for statement in ("CREATE DATABASE restored", *(f'CREATE ROLE "{role}" NOLOGIN' for role in roles)):
            setup = _docker([*psql, "-d", "postgres", "-c", statement])
            if setup.returncode:
                logger.warning("restore_test_database_setup_failed", detail=_first_error(setup.stderr))
                raise RuntimeError("Disposable database setup failed")
        loaded = _docker([*psql, "-d", "restored", "-f", "/restore/database.sql"], timeout=DATABASE_LOAD_TIMEOUT, scratch=scratch)
        if loaded.returncode:
            # Private operator log only: a psql error line may quote row data.
            logger.warning("restore_test_database_load_failed", detail=_first_error(loaded.stderr))
            raise RuntimeError(f"Database dump did not load (psql exit {loaded.returncode})")
        query = (
            "SELECT n.nspname || '.' || c.relname, (xpath('/row/c/text()', query_to_xml("
            "format('SELECT count(*) AS c FROM ONLY %I.%I', n.nspname, c.relname), false, true, '')))[1]::text "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg_toast%'"
        )
        counted = _docker([*psql, "-d", "restored", "-tA", "-F", "\t", "-c", query], timeout=600)
        if counted.returncode:
            raise RuntimeError("Restored row counts could not be read")
        restored = {table: int(count) for table, count in (line.split("\t") for line in str(counted.stdout).splitlines() if "\t" in line)}
    finally:
        removed = subprocess.run([*nightshift_stack.docker_cli(), "rm", "-fv", name], capture_output=True, text=True, timeout=120, check=False)
        if removed.returncode and name in subprocess.run([*nightshift_stack.docker_cli(), "ps", "-aq", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"], capture_output=True, text=True, timeout=60, check=False).stdout:
            logger.warning("restore_test_container_cleanup_failed", container=name)
    mismatches = {table: {"expected": rows, "restored": restored.get(table)} for table, rows in expected.items() if restored.get(table) != rows}
    largest = sorted(expected.items(), key=lambda item: item[1], reverse=True)[:10]
    return {
        "ok": not mismatches and bool(expected), "tables": len(expected), "rows": sum(expected.values()),
        "roles_created": len(roles), "mismatches": mismatches, "largest_tables": dict(largest),
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def restore_test_point(source: Mapping[str, Any], point: Mapping[str, Any]) -> dict[str, Any]:
    """Restore one point from offsite, cross-check a local sample, and load its database."""
    from .backup_repository_runtime import (
        _approved_key_directory,
        _assert_repository_identity,
        _backup_environment,
        _known_restore_bytes,
    )
    from .backup_restic import ResticAdapter, ResticConfig

    verification = point.get("verification_json") or {}
    config = ResticConfig.from_env(_backup_environment(point))
    adapter = ResticAdapter(config)
    _approved_key_directory(config)
    _assert_repository_identity(adapter, verification, remote=True)
    _assert_repository_identity(adapter, verification)
    started = time.monotonic()
    known = _known_restore_bytes(point)
    # Remote payload, local sample, and a repository rebuilt from its bundle.
    with restore_scratch("st-monthly-restore-", required_bytes=3 * known) as scratch:
        remote_target = scratch / "remote"
        local_target = scratch / "local"
        for target in (remote_target, local_target):
            target.mkdir(mode=0o700)
        restored = adapter.restore(str(verification["remote_snapshot_id"]), remote_target, remote=True)
        payload = Path(restored["payload_root"])
        restored_bytes = tree_bytes(payload)
        sample = _sample(payload, str(point["id"]))
        if not sample:
            raise RuntimeError("Restored payload has no files to compare")
        local = adapter.restore(str(verification["snapshot_id"]), local_target, include=sample)
        local_root = Path(local["payload_root"])
        mismatched = [path for path in sample if _sha256(payload / path) != _sha256(local_root / path)]
        evidence: dict[str, Any] = {
            "ok": not mismatched, "method": METHOD, "remote": True, "format": "restic-v1",
            "backup_id": point["id"], "remote_snapshot_id": verification["remote_snapshot_id"],
            "restored_bytes": restored_bytes,
            "checksum_sample": {"files": len(sample), "matched": len(sample) - len(mismatched), "mismatched": mismatched,
                                "reference": "independent local repository"},
        }
        if verification.get("has_db") is True:
            name = str((verification.get("capture") or {}).get("db_dump_name") or "database.sql")
            dump = payload / name
            if Path(name).is_absolute() or ".." in Path(name).parts or not dump.is_file():
                raise RuntimeError("Captured database dump is missing from the restored payload")
            evidence["database"] = verify_database_dump(dump, scratch)
            evidence["ok"] = evidence["ok"] and evidence["database"].get("ok", True)
        git_drill = scratch / "git"
        git_drill.mkdir(mode=0o700)
        evidence["git_history"] = drill_git_history(payload, git_drill)
        evidence["ok"] = evidence["ok"] and evidence["git_history"]["ok"]
    evidence["duration_ms"] = int((time.monotonic() - started) * 1000)
    return evidence


def _record(source: Mapping[str, Any], point: Mapping[str, Any], evidence: dict[str, Any]) -> None:
    source_id = str(source["id"])
    verified_at = datetime.now(UTC).isoformat()
    backup_store.merge_backup_verification_json(str(point["id"]), {"isolated_restore": {**evidence, "verified_at": verified_at}})
    backup_store.update_source_drill_result(source_id=source_id, ok=evidence["ok"] is True, backup_id=str(point["id"]), result=evidence)
    if evidence["ok"] is True or source.get("last_drill_ok") is False:
        return  # Alert once: an already failing source is not re-announced.
    try:
        create_notification(
            project_id="summitflow", notification_type="system", title="Monthly backup restore test failed",
            message=f"The offsite restore test for {source_id} did not pass. Review backup readiness for this source.",
            severity="error", metadata={"backup_event": "failed", "operation": METHOD, "source_id": source_id, "backup_id": point["id"]},
            dedupe_key=f"backup:{METHOD}:{source_id}:failed",
        )
    except Exception:
        logger.warning("monthly_restore_test_notification_failed", source_id=source_id)


def _receipt() -> dict[str, Any]:
    try:
        return json.loads(RECEIPT.read_text())
    except (OSError, ValueError):
        return {}


def run_monthly_offsite_restore_test(*, source_id: str | None = None, force: bool = False) -> dict[str, Any]:
    """Run the rotating monthly restore, or one named source on request."""
    previous = _receipt()
    last = previous.get("completed_at")
    # Only a verified run satisfies the cadence; a failure retries next week.
    if not force and not source_id and previous.get("status") == "verified" and last and datetime.fromisoformat(last) > datetime.now(UTC) - timedelta(days=MONTHLY_CADENCE_DAYS):
        return {"status": "skipped", "reason": "monthly-cadence", "last_completed_at": last}
    from .backup_pinned_restore_test import (
        PINNED_SOURCES,
        pinned_point,
        pinned_selection,
        restore_test_pinned,
    )

    sources = backup_store.list_sources()
    if source_id:
        source = next((item for item in sources if item["id"] == source_id), None)
        point = (pinned_point(source_id) if source_id in PINNED_SOURCES else _offsite_point(source_id)) if source else None
        if source is None or point is None:
            return {"status": "failed", "error": f"No offsite-verified repository point for {source_id}"}
        selected = [(source, point)]
    else:
        # The rotation plus the pinned critical sources it can never reach (guest streams, the hub's large archive).
        rotation = select_rotation(sources)
        chosen = {str(source["id"]) for source, _ in rotation}
        selected = rotation + [item for item in pinned_selection(sources) if str(item[0]["id"]) not in chosen]
    results: dict[str, Any] = {}
    for source, point in selected:
        current = str(source["id"])
        try:
            evidence = restore_test_pinned(source, point) if current in PINNED_SOURCES else restore_test_point(source, point)
        except BackupCancelled:
            raise
        except Exception as exc:
            logger.exception("monthly_restore_test_failed", source_id=current)
            evidence = {"ok": False, "method": METHOD, "backup_id": point["id"], "error": str(exc)[:500]}
        _record(source, point, evidence)
        results[current] = evidence
    status = "failed" if not results or any(item["ok"] is not True for item in results.values()) else "verified"
    receipt = {"status": status, "completed_at": datetime.now(UTC).isoformat(), "sources": results}
    if not source_id:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        temporary = RECEIPT.with_suffix(".tmp")
        temporary.write_text(json.dumps(receipt, indent=1, default=str))
        os.replace(temporary, RECEIPT)
    logger.info("monthly_restore_test_completed", status=status, sources=sorted(results))
    return receipt
