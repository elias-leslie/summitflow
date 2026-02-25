"""Backup Storage - Database operations for backup management.

This package handles all database interactions for:
- CRUD operations for backups
- Backup status tracking
- Backup source registration and scheduling
"""

from __future__ import annotations

from .crud import (
    create_backup_record,
    delete_backup_record,
    get_backup,
    list_backups,
    update_backup_status,
)
from .queries import (
    cleanup_expired_backup_records,
    cleanup_stale_backup_records,
    get_latest_backup,
    get_storage_summary,
)
from .sources import (
    create_source,
    delete_source,
    get_source,
    list_due_sources,
    list_sources,
    update_source,
    update_source_last_run,
)

__all__ = [
    "cleanup_expired_backup_records",
    "cleanup_stale_backup_records",
    "create_backup_record",
    "create_source",
    "delete_backup_record",
    "delete_source",
    "get_backup",
    "get_latest_backup",
    "get_source",
    "get_storage_summary",
    "list_backups",
    "list_due_sources",
    "list_sources",
    "update_backup_status",
    "update_source",
    "update_source_last_run",
]
