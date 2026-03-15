"""Backup Management API - Create, list, and restore backups.

This module provides REST API endpoints for:
- Creating and listing backups (per-project and global)
- Restoring from backups
- Managing backup sources and schedules
- Storage backend management
- Backup health monitoring
- Viewing storage usage
"""

from fastapi import APIRouter

from .global_endpoints import router as global_router
from .health_endpoints import router as health_router
from .models import (
    BackupCreate,
    BackupHealthItem,
    BackupHealthResponse,
    BackupListResponse,
    BackupResponse,
    BackupSourceCreate,
    BackupSourceResponse,
    BackupSourceUpdate,
    RestoreRequest,
    RestoreResponse,
    StorageBackendCreate,
    StorageBackendResponse,
    StorageBackendUpdate,
    StorageSummaryResponse,
)
from .project_endpoints import router as project_router
from .source_endpoints import router as source_router
from .storage_endpoints import router as storage_router
from .wal_endpoints import router as wal_router

# Main router that combines all sub-routers
router = APIRouter()

# Include routers (order matters: storage and health before source/project to avoid path conflicts)
router.include_router(storage_router)
router.include_router(health_router)
router.include_router(wal_router)
router.include_router(source_router)
router.include_router(project_router)
router.include_router(global_router)

__all__ = [
    "BackupCreate",
    "BackupHealthItem",
    "BackupHealthResponse",
    "BackupListResponse",
    "BackupResponse",
    "BackupSourceCreate",
    "BackupSourceResponse",
    "BackupSourceUpdate",
    "RestoreRequest",
    "RestoreResponse",
    "StorageBackendCreate",
    "StorageBackendResponse",
    "StorageBackendUpdate",
    "StorageSummaryResponse",
    "router",
]
