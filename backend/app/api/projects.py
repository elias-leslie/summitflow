"""Projects API - Register and manage target applications.

This module re-exports the projects package for backward compatibility.
The actual implementation is in the projects/ package.
"""

from .projects import (
    DEFAULT_AUTOMATION_SETTINGS,
    AgentConfigResponse,
    AgentConfigUpdate,
    AutomationSettings,
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
    "DEFAULT_AUTOMATION_SETTINGS",
    "AgentConfigResponse",
    "AgentConfigUpdate",
    "AutomationSettings",
    "ProjectCreate",
    "ProjectHealthResponse",
    "ProjectResponse",
    "ProjectStats",
    "ProjectUpdate",
    "ProjectWithStats",
    "ProjectsWithStatsResponse",
    "router",
]
