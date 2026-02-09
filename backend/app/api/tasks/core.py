"""Tasks API - Core CRUD operations.

This module is a router aggregator that imports endpoints from specialized modules:
- list_endpoints: List tasks with various filters (list_tasks, list_ready_tasks, list_blocked_tasks)
- get_endpoints: Get task by ID (get_task_global, get_task, check_completion_readiness)
- create_endpoints: Create tasks (create_task, batch_create_tasks)
- update_endpoints: Update/delete/status (update_task, delete_task, update_task_status, execute_task)

All endpoints remain importable from this module for backward compatibility.
"""

from __future__ import annotations

from fastapi import APIRouter

# Import all endpoints and routers from specialized modules
from .create_endpoints import batch_create_tasks, create_task
from .create_endpoints import router as create_router
from .get_endpoints import check_completion_readiness, get_task, get_task_global
from .get_endpoints import router as get_router
from .list_endpoints import list_blocked_tasks, list_ready_tasks, list_tasks
from .list_endpoints import router as list_router
from .update_endpoints import delete_task, execute_task, update_task, update_task_status
from .update_endpoints import router as update_router

# Create the main router and include all sub-routers
router = APIRouter()

router.include_router(list_router)
router.include_router(get_router)
router.include_router(create_router)
router.include_router(update_router)

# Re-export all endpoint functions for backward compatibility
__all__ = [
    "batch_create_tasks",
    "check_completion_readiness",
    "create_task",
    "delete_task",
    "execute_task",
    "get_task",
    "get_task_global",
    "list_blocked_tasks",
    "list_ready_tasks",
    "list_tasks",
    "router",
    "update_task",
    "update_task_status",
]
