"""Tasks API package - Agent execution task management for projects.

Split from monolithic tasks.py (1981 lines) into focused modules:
- core.py: CRUD operations, helpers
- dependencies.py: Task dependency management
- enrichment.py: AI-powered task enrichment
- subtasks.py: Subtask management
- steps.py: Step management within subtasks (with verify_command support)
- logging.py: Progress logging, SSE streaming, task claiming
- autocode.py: AI worker execution endpoint
"""

from fastapi import APIRouter

from .autocode import router as autocode_router
from .core import router as core_router
from .dependencies import router as dependencies_router
from .enrichment import router as enrichment_router
from .logging import router as logging_router
from .steps import router as steps_router
from .subtasks import router as subtasks_router
from .workflow import router as workflow_router

router = APIRouter()

# Include all sub-routers
router.include_router(core_router)
router.include_router(dependencies_router)
router.include_router(enrichment_router)
router.include_router(subtasks_router)
router.include_router(steps_router)
router.include_router(logging_router)
router.include_router(autocode_router)
router.include_router(workflow_router)

__all__ = ["router"]
