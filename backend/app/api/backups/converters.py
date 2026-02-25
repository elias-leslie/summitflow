"""Data conversion utilities for backup API."""

from datetime import datetime

from .models import BackupResponse


def backup_to_response(backup: dict[str, object]) -> BackupResponse:
    """Convert backup dict to response model."""
    return BackupResponse(
        id=str(backup["id"]),
        project_id=str(backup["project_id"]),
        name=str(backup["name"]),
        backup_type=str(backup["backup_type"]),
        status=str(backup["status"]),
        size_bytes=_get_int_or_none(backup, "size_bytes"),
        db_size_bytes=_get_int_or_none(backup, "db_size_bytes"),
        files_size_bytes=_get_int_or_none(backup, "files_size_bytes"),
        location=_get_str_or_none(backup, "location"),
        note=_get_str_or_none(backup, "note"),
        created_at=_parse_datetime(backup, "created_at"),
        started_at=_parse_datetime(backup, "started_at"),
        completed_at=_parse_datetime(backup, "completed_at"),
        error_message=_get_str_or_none(backup, "error_message"),
        verified=_get_bool_or_none(backup, "verified"),
        verified_at=_parse_datetime(backup, "verified_at"),
        checksum=_get_str_or_none(backup, "checksum"),
        total_files=_get_int_or_none(backup, "total_files"),
        verification_json=_get_dict_or_none(backup, "verification_json"),
        source_id=_get_str_or_none(backup, "source_id"),
    )


def _parse_datetime(data: dict[str, object], key: str) -> datetime | None:
    """Parse ISO datetime string from dict."""
    value = data.get(key)
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _get_int_or_none(data: dict[str, object], key: str) -> int | None:
    """Get int value or None from dict."""
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, int):
        return value
    return int(str(value))


def _get_str_or_none(data: dict[str, object], key: str) -> str | None:
    """Get str value or None from dict."""
    value = data.get(key)
    return str(value) if value is not None else None


def _get_bool_or_none(data: dict[str, object], key: str) -> bool | None:
    """Get bool value or None from dict."""
    value = data.get(key)
    return bool(value) if value is not None else None


def _get_dict_or_none(data: dict[str, object], key: str) -> dict[str, object] | None:
    """Get dict value or None from dict."""
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    return {str(k): v for k, v in value.items()}
