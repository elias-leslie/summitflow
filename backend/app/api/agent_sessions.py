"""Managed Codex operator API (status and owner actions)."""

import importlib
import sqlite3
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .backups.key_endpoints import _require_same_origin
from .monitor import require_monitor_owner

router = APIRouter()


def _managed_owner():
    """Load the same host execution-owner interface used by the existing CLI."""
    scripts = Path(__file__).resolve().parents[3] / "scripts" / "lib"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return importlib.import_module("codex_managed_delivery")


@router.get("/managed-codex", dependencies=[Depends(require_monitor_owner)])
def managed_codex_status(response: Response, project_id: str | None = None) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _managed_owner().operator_status(project_id=project_id)
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Managed Codex local owner unavailable") from error


@router.post("/{project_id}/managed-codex/{action}", dependencies=[Depends(require_monitor_owner)])
def managed_codex_action(project_id: str, action: Literal["disable", "enable", "drain", "check-update", "stage-update", "qualify-update", "promote-update", "rollback-update"], request: Request, response: Response) -> dict:
    _require_same_origin(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return _managed_owner().operator_action(action, project_id=project_id)
    except ValueError as error:
        update_error = getattr(_managed_owner(), "ManagedUpdateError", type(None))
        if isinstance(error, update_error):
            raise HTTPException(status_code=409, detail=f"Managed Codex update failed: {error.code} ({error.stage})") from error
        raise HTTPException(status_code=409, detail="Managed Codex owner or project binding unavailable") from error
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Managed Codex local owner unavailable") from error

