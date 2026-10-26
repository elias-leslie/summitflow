"""Backups other projects run and the Proxmox freshness receipt."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/backups/external")
async def external_backups() -> dict[str, Any]:
    """Backups other projects run (Blackbox archive pull, Portfolio-AI artifacts) and whether each is fresh."""
    from ...tasks.backup_alerts import external_statuses

    now = datetime.now(UTC)
    statuses = await asyncio.to_thread(external_statuses, now)
    return {"generated_at": now.isoformat(), "sources": [{"id": key, **value} for key, value in sorted(statuses.items())]}


@router.get("/backups/proxmox/freshness")
async def proxmox_freshness() -> dict[str, Any]:
    """Whether every covered Proxmox guest and the cluster config has a current backup in Google Drive."""
    from ...tasks.backup_proxmox import freshness_receipt

    return await asyncio.to_thread(freshness_receipt)
