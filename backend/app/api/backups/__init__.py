"""Backup API: the overview of the two recovery layers, host status, external sources and encryption keys."""

from fastapi import APIRouter

from .external_endpoints import router as external_router
from .key_endpoints import router as key_router
from .native_host_endpoints import router as native_host_router
from .overview_endpoints import router as overview_router

router = APIRouter()
router.include_router(key_router)
router.include_router(native_host_router)
router.include_router(overview_router)
router.include_router(external_router)

__all__ = ["router"]
