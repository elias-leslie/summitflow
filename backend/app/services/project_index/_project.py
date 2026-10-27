"""Project registration lookups shared by `.index.yaml` generation and page discovery."""

from __future__ import annotations

from typing import Any

from ...storage.connection import get_cursor
from ...utils._git_core import _translate_path

_PROJECT_COLUMNS = ("root_path", "base_url", "frontend_port", "backend_port")


def get_project_config(project_id: str) -> dict[str, Any] | None:
    """Return the registration fields the index needs, or None for an unknown project.

    ``root_path`` is translated for Docker mounts so callers can read the checkout directly.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT root_path, base_url, frontend_port, backend_port FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    config = dict(zip(_PROJECT_COLUMNS, row, strict=True))
    if config["root_path"]:
        config["root_path"] = str(_translate_path(config["root_path"]))
    return config


def get_project_root(project_id: str) -> str | None:
    """Return the registered project root, or None when unknown or unset."""
    config = get_project_config(project_id)
    return (config or {}).get("root_path") or None
