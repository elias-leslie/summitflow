"""Backup Management API - Create, list, and restore backups.

This module provides REST API endpoints for:
- Creating and listing backups (per-project and global)
- Restoring from backups
- Managing backup schedules
- Viewing storage usage
"""

from fastapi import APIRouter

from .global_endpoints import router as global_router
from .models import (
    BackupCreate,
    BackupListResponse,
    BackupResponse,
    RestoreRequest,
    RestoreResponse,
    ScheduleRequest,
    ScheduleResponse,
    StorageSummaryResponse,
)
from .project_endpoints import router as project_router
from .schedule_endpoints import router as schedule_router

# Main router that combines all sub-routers
router = APIRouter()

# Include routers in order (schedule MUST come before project to avoid path conflicts)
router.include_router(schedule_router)
router.include_router(project_router)
router.include_router(global_router)

# Re-export models for backward compatibility
__all__ = [
    "router",
    "BackupCreate",
    "BackupResponse",
    "BackupListResponse",
    "RestoreRequest",
    "RestoreResponse",
    "ScheduleRequest",
    "ScheduleResponse",
    "StorageSummaryResponse",
]
