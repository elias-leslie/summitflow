"""Utility functions for backup operations."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from ..logging_config import get_logger
from ..project_identity import get_project_upload_dir_name
from ..storage.connection import get_cursor

logger = get_logger(__name__)

# Docker path translation for host-mounted directories
_HOST_HOME_PATH = os.environ.get("HOST_HOME_PATH", "")
_DOCKER_HOME_MOUNT = os.environ.get("BACKUP_HOST_ROOT", "")


def _translate_path(raw: str | None) -> str | None:
    """Translate host path to Docker mount path if running in Docker."""
    if raw and _HOST_HOME_PATH and _DOCKER_HOME_MOUNT and raw.startswith(_HOST_HOME_PATH):
        return _DOCKER_HOME_MOUNT + raw[len(_HOST_HOME_PATH):]
    return raw


def _path_exists(*paths: str | None) -> bool:
    """Return True when any candidate path exists on disk."""
    return any(path and Path(path).exists() for path in paths)


def _resolve_legacy_upload_path(source_id: str) -> str | None:
    """Resolve renamed upload workspace sources from project identity metadata."""
    suffix = "-uploads"
    if not source_id.endswith(suffix):
        return None

    project_id = source_id[: -len(suffix)]
    upload_dir_name = get_project_upload_dir_name(project_id)
    if not upload_dir_name:
        return None

    home_roots: list[str] = []
    for candidate in (_HOST_HOME_PATH, os.environ.get("HOME"), str(Path.home())):
        if candidate and candidate not in home_roots:
            home_roots.append(candidate)

    for home_root in home_roots:
        raw_candidate = str(Path(home_root) / upload_dir_name)
        translated_candidate = _translate_path(raw_candidate)
        if _path_exists(raw_candidate, translated_candidate):
            return translated_candidate or raw_candidate

    return None


def get_source_path(source_id: str) -> str | None:
    """Get path for a backup source."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT path FROM backup_sources WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()

    raw_path = row[0] if row and row[0] else None
    translated_path = _translate_path(raw_path)
    if _path_exists(raw_path, translated_path):
        return translated_path

    fallback_path = _resolve_legacy_upload_path(source_id)
    if fallback_path:
        logger.info(
            "backup_source_path_fallback",
            source_id=source_id,
            configured_path=raw_path,
            resolved_path=fallback_path,
        )
        return fallback_path

    return translated_path


def get_project_root(project_id: str) -> str | None:
    """Get root_path for a project. Falls back to backup_sources path."""
    # Try backup_sources first (handles non-project sources)
    source_path = get_source_path(project_id)
    if source_path:
        return source_path

    with get_cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        return _translate_path(row[0]) if row and row[0] else None


def _parse_backup_line(line: str, result: dict[str, Any]) -> None:
    """Parse a single historical backup output line and update result in place."""
    line = line.strip()

    if line.startswith("Size:"):
        result["total_bytes"] = parse_size(line.split(":", 1)[1].strip())
        return

    if line.startswith("DB Size:"):
        result["db_bytes"] = parse_size(line.split(":", 1)[1].strip())
        return

    if line.startswith("Location:"):
        result["location"] = line.split(":", 1)[1].strip()
        return

    if line.startswith("Archive:"):
        result["archive_name"] = line.split(":", 1)[1].strip()
        return

    if line.startswith("Pending:"):
        result["pending_path"] = line.split(":", 1)[1].strip()
        return

    if not line.startswith("Verification:"):
        return

    json_str = line.split(":", 1)[1].strip()
    try:
        result["verification"] = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        logger.warning("failed_to_parse_verification_json", raw=json_str[:200])


def parse_backup_output(output: str) -> dict[str, Any]:
    """Parse historical backup output for size, location, and verification info."""
    result: dict[str, Any] = {}
    for line in output.split("\n"):
        _parse_backup_line(line, result)
    return result


def _parse_bytes_literal(size_str: str) -> int | None:
    """Parse a size string containing the word 'bytes'."""
    try:
        return int(size_str.replace("bytes", "").strip())
    except ValueError:
        return None


def _parse_suffix_size(size_str: str) -> int | None:
    """Parse a size string with a unit suffix like K, M, G, T."""
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for suffix, mult in multipliers.items():
        if not size_str.endswith(suffix):
            continue
        try:
            return int(float(size_str[:-1]) * mult)
        except ValueError:
            return None
    return None


def parse_size(size_str: str) -> int | None:
    """Parse size string like '123M', '1.5G', or '123456 bytes'."""
    size_str = size_str.strip()

    if "bytes" in size_str:
        return _parse_bytes_literal(size_str)

    suffix_result = _parse_suffix_size(size_str)
    if suffix_result is not None:
        return suffix_result

    try:
        return int(size_str)
    except ValueError:
        return None


def build_script_error_message(result: subprocess.CompletedProcess[str]) -> str:
    """Build an informative error message from a failed subprocess result."""
    stderr_clean = result.stderr or ""
    stderr_lines = [ln for ln in stderr_clean.splitlines() if not ln.strip().startswith("putting file")]
    stderr_filtered = "\n".join(stderr_lines).strip()
    stdout_tail = (result.stdout or "")[-500:].strip()
    parts = [f"rc={result.returncode}"]
    if stderr_filtered:
        parts.append(f"stderr: {stderr_filtered}")
    if stdout_tail:
        parts.append(f"stdout(tail): {stdout_tail}")
    return " | ".join(parts) if any([stderr_filtered, stdout_tail]) else "Unknown error"


def as_mapping(value: object) -> Mapping[str, Any] | None:
    """Return a string-keyed mapping view when the value is JSON-like."""
    return cast(Mapping[str, Any], value) if isinstance(value, Mapping) else None


def get_int_field(data: Mapping[str, Any], key: str) -> int | None:
    """Return an int field from a JSON-like mapping when coercion is safe."""
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        return int(stripped) if stripped.isdigit() else None
    return None


def get_str_field(data: Mapping[str, Any], key: str) -> str | None:
    """Return a string field from a JSON-like mapping when present."""
    value = data.get(key)
    if value is None:
        return None
    return str(value)


def get_bool_field(data: Mapping[str, Any], key: str) -> bool | None:
    """Return a bool field from a JSON-like mapping when coercion is safe."""
    value = data.get(key)
    if isinstance(value, bool):
        return value
    return None


def build_verification_kwargs(verification: Mapping[str, Any]) -> dict[str, Any]:
    """Extract verification fields into update_backup_status kwargs."""
    vkw: dict[str, Any] = {
        "verified": get_bool_field(verification, "verified"),
        "verified_at": get_str_field(verification, "verified_at"),
        "checksum": get_str_field(verification, "checksum"),
        "verification_json": dict(verification),
    }
    total = get_int_field(verification, "total_files")
    if total is not None:
        vkw["total_files"] = total
    return vkw


def require_verified_backup_output(output: Mapping[str, Any]) -> None:
    """Fail closed unless a native backup reports successful verification."""
    verification = as_mapping(output.get("verification"))
    if verification and get_bool_field(verification, "verified") is True:
        return
    errors = verification.get("errors") if verification else None
    detail = (
        "; ".join(str(error) for error in errors if error)
        if isinstance(errors, list)
        else ""
    )
    raise RuntimeError(
        "Backup archive verification failed"
        + (f": {detail}" if detail else ": verification result missing or unverified")
    )


_FREQUENCY_DELTAS: dict[str, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


def calculate_next_run(frequency: str) -> datetime:
    """Calculate next run time based on frequency."""
    now = datetime.now(UTC)
    delta = _FREQUENCY_DELTAS.get(frequency, timedelta(days=1))
    return now + delta


def get_source_type(source_id: str) -> str | None:
    """Get the source_type for a backup source."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT source_type FROM backup_sources WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else None


def get_storage_config(source_id: str) -> dict[str, Any] | None:
    """Resolve storage config: source → default backend → env/files.

    Checks if the source has a storage_backend_id, then falls back to the
    default backend, then returns None (caller uses env/file-based config).
    """
    with get_cursor() as cur:
        # Check source-specific backend
        cur.execute(
            """
            SELECT sb.backend_type, sb.config FROM storage_backends sb
            JOIN backup_sources bs ON bs.storage_backend_id = sb.id
            WHERE bs.id = %s AND sb.enabled = TRUE
            """,
            (source_id,),
        )
        row = cur.fetchone()
        if row and row[1]:
            config = row[1] if isinstance(row[1], dict) else None
            if config is not None:
                return {**config, "__backend_type": row[0]}

        # Fall back to default backend
        cur.execute(
            "SELECT backend_type, config FROM storage_backends WHERE is_default = TRUE AND enabled = TRUE LIMIT 1"
        )
        row = cur.fetchone()
        if row and row[1]:
            config = row[1] if isinstance(row[1], dict) else None
            if config is not None:
                return {**config, "__backend_type": row[0]}

    return None


def build_storage_env(source_id: str) -> dict[str, str]:
    """Resolve storage backend config and return as env var overrides.

    Returns a dict of storage env vars that can be passed as
    extra env vars to subprocess calls. Returns empty dict if no backend
    is configured (scripts will use their own env/file-based config).
    """
    config = get_storage_config(source_id)
    if not config:
        return {}

    env_map: dict[str, str] = {}
    backend_type = str(config.get("__backend_type") or config.get("backend_type") or "smb")
    env_map["STORAGE_BACKEND_TYPE"] = backend_type
    if config.get("host"):
        env_map["SMB_HOST"] = str(config["host"])
    if config.get("share"):
        env_map["SMB_SHARE"] = str(config["share"])
    if config.get("path"):
        env_map["SMB_PATH"] = str(config["path"])
        env_map["LOCAL_BACKUP_PATH"] = str(config["path"])
    if config.get("root_path"):
        env_map["LOCAL_BACKUP_ROOT"] = str(config["root_path"])
    if config.get("base_path"):
        env_map["LOCAL_BACKUP_ROOT"] = str(config["base_path"])
    if config.get("user"):
        env_map["SMB_USER"] = str(config["user"])
    if config.get("credentials_file"):
        env_map["CREDENTIALS_FILE"] = str(config["credentials_file"])

    return env_map
