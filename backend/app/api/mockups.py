"""Mockups API endpoints.

Provides CRUD operations for design mockups:
- Create, read, update, delete mockups
- List mockups with filtering
- Approval workflow
- Mockup history/iterations
"""

from fastapi import APIRouter

from . import mockups_analysis, mockups_crud, mockups_generation, mockups_task_page

# Re-export models for backwards compatibility
from .mockups_models import (
    AnalyzePageRequest,
    AnalyzePageResponse,
    MockupCreate,
    MockupListResponse,
    MockupResponse,
    MockupStatsResponse,
    MockupStatusUpdate,
    MockupUpdate,
    RerunMockupRequest,
    RerunMockupResponse,
)

# Create main router and include sub-routers
router = APIRouter(tags=["mockups"])
router.include_router(mockups_crud.router)
router.include_router(mockups_task_page.router)
router.include_router(mockups_analysis.router)
router.include_router(mockups_generation.router)

# Re-export for backwards compatibility
__all__ = [
    "AnalyzePageRequest",
    "AnalyzePageResponse",
    "MockupCreate",
    "MockupListResponse",
    "MockupResponse",
    "MockupStatsResponse",
    "MockupStatusUpdate",
    "MockupUpdate",
    "RerunMockupRequest",
    "RerunMockupResponse",
    "router",
]
