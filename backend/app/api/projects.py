"""Projects API - Register and manage target applications.

This module re-exports the projects package for backward compatibility.
The actual implementation is in the projects/ package.
"""

from .projects import (
    AgentConfigResponse,
    AgentConfigUpdate,
    ProjectCreate,
    ProjectHealthResponse,
    ProjectResponse,
    ProjectStats,
    ProjectsWithStatsResponse,
    ProjectUpdate,
    ProjectWithStats,
    router,
)

__all__ = [
    "AgentConfigResponse",
    "AgentConfigUpdate",
    "ProjectCreate",
    "ProjectHealthResponse",
    "ProjectResponse",
    "ProjectStats",
    "ProjectUpdate",
    "ProjectWithStats",
    "ProjectsWithStatsResponse",
    "router",
]
