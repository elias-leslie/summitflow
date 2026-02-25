"""Backup Management API - Create, list, and restore backups.

This module provides REST API endpoints for:
- Creating and listing backups (per-project and global)
- Restoring from backups
- Managing backup sources and schedules
- Viewing storage usage

Re-exports all functionality from the backups package.
"""

# Import router from the package
from .backups import (
    BackupCreate,
    BackupListResponse,
    BackupResponse,
    BackupSourceCreate,
    BackupSourceResponse,
    BackupSourceUpdate,
    RestoreRequest,
    RestoreResponse,
    StorageSummaryResponse,
    router,
)

__all__ = [
    "BackupCreate",
    "BackupListResponse",
    "BackupResponse",
    "BackupSourceCreate",
    "BackupSourceResponse",
    "BackupSourceUpdate",
    "RestoreRequest",
    "RestoreResponse",
    "StorageSummaryResponse",
    "router",
]
