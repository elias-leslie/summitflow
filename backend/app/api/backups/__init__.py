"""Backup Management API - Create, list, and restore backups.

This module provides REST API endpoints for:
- Creating and listing backups (per-project and global)
- Restoring from backups
- Managing backup sources and schedules
- Viewing storage usage
"""

from fastapi import APIRouter

from .global_endpoints import router as global_router
from .models import (
    BackupCreate,
    BackupListResponse,
    BackupResponse,
    BackupSourceCreate,
    BackupSourceResponse,
    BackupSourceUpdate,
    RestoreRequest,
    RestoreResponse,
    StorageSummaryResponse,
)
from .project_endpoints import router as project_router
from .source_endpoints import router as source_router

# Main router that combines all sub-routers
router = APIRouter()

# Include routers (source MUST come before project to avoid path conflicts)
router.include_router(source_router)
router.include_router(project_router)
router.include_router(global_router)

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
