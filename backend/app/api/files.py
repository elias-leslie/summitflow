"""File browser API — browse and read project files.

Endpoints:
- GET /{project_id}/files/tree?path= — Directory listing (lazy-load for tree)
- GET /{project_id}/files/content?path= — File content with language detection
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services import file_browser
from .dependencies import ValidProject

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{project_id}/files/tree")
def get_file_tree(
    project: ValidProject,
    path: str = Query("", description="Relative directory path (empty = root)"),
) -> dict[str, Any]:
    """List directory entries for file tree navigation."""
    root_path = project["root_path"]
    if not root_path:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    try:
        return file_browser.list_directory(root_path, path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{project_id}/files/content")
def get_file_content(
    project: ValidProject,
    path: str = Query(..., description="Relative file path"),
) -> dict[str, Any]:
    """Read file content with binary detection and syntax highlighting info."""
    root_path = project["root_path"]
    if not root_path:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    try:
        return file_browser.read_file(root_path, path)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
