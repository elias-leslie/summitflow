"""Backup Storage - Database operations for backup management.

This package handles all database interactions for backup records:
- CRUD operations for backups
- Backup status tracking
- Schedule configuration
"""

from __future__ import annotations

# Re-export all public functions to maintain backward compatibility
from .crud import (
    create_backup_record,
    delete_backup_record,
    get_backup,
    list_backups,
    update_backup_status,
)
from .queries import cleanup_stale_backup_records, get_latest_backup, get_storage_summary
from .schedules import get_schedule, list_due_schedules, update_schedule_last_run, upsert_schedule

__all__ = [
    "cleanup_stale_backup_records",
    "create_backup_record",
    "delete_backup_record",
    "get_backup",
    "get_latest_backup",
    "get_schedule",
    "get_storage_summary",
    "list_backups",
    "list_due_schedules",
    "update_backup_status",
    "update_schedule_last_run",
    "upsert_schedule",
]
