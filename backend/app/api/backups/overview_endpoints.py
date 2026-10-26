"""The backup picture: local btrbk points, the daily Google Drive copy, and what the retired shape left behind."""

import asyncio
from typing import Any

from fastapi import APIRouter

from ...tasks.backup_overview import overview
from ...tasks.backup_run import request_run

router = APIRouter()


@router.get("/backups/overview")
async def backup_overview(points: bool = True) -> dict[str, Any]:
    return await asyncio.to_thread(overview, points=points)


@router.post("/backups/run")
async def run_backup_now(offsite: bool = False) -> dict[str, Any]:
    """Start a backup run now under the same limits as the 4-hourly timer; ``offsite`` also makes today's Google Drive copy."""
    return await asyncio.to_thread(request_run, with_offsite=offsite)
