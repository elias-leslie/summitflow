"""Live frontend page discovery from a project checkout.

Supports Next.js app router (``page.tsx`` under ``frontend/app`` or ``frontend/src/app``)
and falls back to a single-page app with ``index.html`` at the project root.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ._project import get_project_config
from .port_detection import get_services

logger = get_logger(__name__)

FRONTEND_DIR = "frontend"
_APP_DIR_CANDIDATES = ("app", "src/app")


def _page_route(page_file: Path, app_dir: Path) -> tuple[str, str]:
    """Return (route path, display name) for a Next.js page file."""
    rel_path = page_file.parent.relative_to(app_dir)
    route = re.sub(r"\[([^\]]+)\]", r":\1", "/" + rel_path.as_posix())
    # Next.js route groups — parenthesised dirs like (app) — do not appear in URLs.
    route = re.sub(r"/\([^)]+\)", "", route)
    path = "/" if route in ("/.", "") else route
    name = page_file.parent.name
    if name.startswith("[") and name.endswith("]"):
        name = f"{page_file.parent.parent.name}/:{name[1:-1]}"
    elif not name or name == "." or path == "/":
        name = "home"
    return path, name


def _find_app_dir(root: Path) -> Path | None:
    for subpath in _APP_DIR_CANDIDATES:
        candidate = root / FRONTEND_DIR / subpath
        if candidate.exists():
            return candidate
    return None


def _resolve_frontend(project_id: str, config: dict[str, Any]) -> tuple[int | None, str | None]:
    """Return (frontend port, page base URL); registration wins, port detection fills gaps."""
    base_url = str(config["base_url"]).rstrip("/") if config.get("base_url") else None
    try:
        port = int(config["frontend_port"]) if config.get("frontend_port") else None
    except (TypeError, ValueError):
        port = None
    if port is None:
        detected = get_services(project_id).get("frontend_port")
        port = detected if isinstance(detected, int) else None
        if not base_url and port is not None:
            base_url = f"http://localhost:{port}"
    return port, base_url


def _page(path: str, name: str, base_url: str | None, port: int | None) -> dict[str, Any]:
    return {"path": path, "name": name, "url": f"{base_url}{path}" if base_url else None, "port": port}


def discover_pages(project_id: str) -> list[dict[str, Any]]:
    """Discover the project's frontend pages from the filesystem, sorted by path.

    Items: ``{"path": str, "name": str, "url": str | None, "port": int | None}``.
    Returns an empty list for unknown projects or projects without a root.
    """
    config = get_project_config(project_id)
    if not config or not config.get("root_path"):
        return []
    root = Path(config["root_path"])
    app_dir = _find_app_dir(root)
    has_spa = (root / "index.html").exists()
    if not app_dir and not has_spa:
        return []

    port, base_url = _resolve_frontend(project_id, config)
    pages: dict[str, dict[str, Any]] = {}
    if app_dir:
        for page_file in app_dir.rglob("page.tsx"):
            try:
                path, name = _page_route(page_file, app_dir)
            except ValueError as exc:
                logger.warning("Failed to resolve page %s: %s", page_file, exc)
                continue
            pages.setdefault(path, _page(path, name, base_url, port))
    if not pages and has_spa:
        pages["/"] = _page("/", "home", base_url, port)
    return [pages[path] for path in sorted(pages)]
