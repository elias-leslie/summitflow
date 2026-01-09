"""Evidence API - Evidence capture and retrieval for capability verification.

This package provides REST API endpoints for evidence:
- GET/POST evidence capture and retrieval
- User and AI review submission
- Configuration management
- Regression detection and review
"""

from fastapi import APIRouter

from . import capture, client_capture, config, core, regressions, review
from .core import _format_evidence_record

router = APIRouter()

# Include all sub-routers
router.include_router(core.router, tags=["evidence"])
router.include_router(client_capture.router, tags=["evidence"])
router.include_router(review.router, tags=["evidence"])
router.include_router(capture.router, tags=["evidence"])
router.include_router(config.router, tags=["evidence"])
router.include_router(regressions.router, tags=["evidence"])

__all__ = ["_format_evidence_record", "router"]
