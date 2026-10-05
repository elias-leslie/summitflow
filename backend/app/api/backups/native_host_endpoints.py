"""Read-only Linux native host recovery status."""

import asyncio
from typing import Any

from fastapi import APIRouter

from ...tasks.backup_btrbk import native_host_status

router = APIRouter()


@router.get("/backups/native-host")
async def native_host_backup_status() -> dict[str, Any]:
    return await asyncio.to_thread(native_host_status)
