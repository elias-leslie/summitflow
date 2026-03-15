"""Backup Storage - Database operations for backup management.

This package handles all database interactions for:
- CRUD operations for backups
- Backup status tracking
- Backup source registration and scheduling
- Storage backend management
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
    get_backup_health_summary,
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
from .storage_backends import (
    create_backend,
    delete_backend,
    get_backend,
    get_default_backend,
    list_backends,
    update_backend,
    update_test_result,
)

__all__ = [
    "cleanup_expired_backup_records",
    "cleanup_stale_backup_records",
    "create_backend",
    "create_backup_record",
    "create_source",
    "delete_backend",
    "delete_backup_record",
    "delete_source",
    "get_backend",
    "get_backup",
    "get_backup_health_summary",
    "get_default_backend",
    "get_latest_backup",
    "get_source",
    "get_storage_summary",
    "list_backends",
    "list_backups",
    "list_due_sources",
    "list_sources",
    "update_backend",
    "update_backup_status",
    "update_source",
    "update_source_last_run",
    "update_test_result",
]
