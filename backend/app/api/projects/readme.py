"""Read the registered checkout's root README for the project overview."""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from ...services import file_browser
from .db_helpers import get_project_from_db

router = APIRouter()


class ProjectReadmeResponse(BaseModel):
    project_id: str
    status: Literal["available", "missing", "unavailable"]
    content: str | None = None


def read_project_readme(project_id: str, root_path: str | None) -> ProjectReadmeResponse:
    """Reuse bounded file reads; never follow a README alias to another file."""
    result = ProjectReadmeResponse(project_id=project_id, status="unavailable")
    if not root_path:
        return result
    root = Path(root_path)
    target = root / "README.md"
    try:
        if not root.is_dir() or target.is_symlink():
            return result
        if not target.exists():
            result.status = "missing"
            return result
        data = file_browser.read_file(root, "README.md")
        if data["is_binary"] or data["truncated"]:
            return result
        content = data["content"]
        if isinstance(content, str):
            result.status = "available"
            result.content = content
    except (OSError, ValueError):
        return result
    return result


@router.get("/{project_id}/readme", response_model=ProjectReadmeResponse)
def get_project_readme(project_id: str) -> ProjectReadmeResponse:
    """Serve current README content from the canonical registered checkout."""
    project = get_project_from_db(project_id)
    return read_project_readme(project.id, project.root_path)
