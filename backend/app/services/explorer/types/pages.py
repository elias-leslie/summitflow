"""Page scanner for Explorer.

Scans frontend pages for the explorer_entries table.
Supports Next.js app router (page.tsx) and simple SPAs (index.html).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_config
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from ..port_detection import get_services

logger = get_logger(__name__)

_HEALTH_KEYS = ("http_status", "response_time_ms", "console_errors", "console_warnings", "last_health_check")
_HEALTH_DEFAULTS: dict[str, None] = dict.fromkeys(_HEALTH_KEYS)


def _calculate_level(path: str) -> int:
    """Return hierarchy level (1-based) from path depth."""
    return 1 if path == "/" else len([s for s in path.split("/") if s]) + 1


def _calculate_parent_path(path: str) -> str | None:
    """Return parent path or None for root."""
    if path == "/":
        return None
    segs = [s for s in path.split("/") if s]
    return "/" if len(segs) <= 1 else "/" + "/".join(segs[:-1])


def _build_nextjs_entry(
    page_file: Path,
    app_dir: Path,
    root_path: Path,
    page_base_url: str | None,
    frontend_port: int | None,
) -> ExplorerEntryCreate:
    """Build an ExplorerEntryCreate for a Next.js page file."""
    rel_path = page_file.parent.relative_to(app_dir)
    route = re.sub(r"\[([^\]]+)\]", r":\1", "/" + str(rel_path).replace("\\", "/"))
    route = route.replace("/(", "/").replace(")/", "/")
    display_path = "/" if route == "/." else route
    name = page_file.parent.name
    if name.startswith("[") and name.endswith("]"):
        name = f"{page_file.parent.parent.name}/:{name[1:-1]}"
    elif not name or name == ".":
        name = "home"
    return ExplorerEntryCreate(
        path=display_path,
        name=name,
        health_status="unknown",
        metadata={
            "method": "GET",
            "port": frontend_port,
            "url": f"{page_base_url}{display_path}" if page_base_url else None,
            "source_file": str(page_file.relative_to(root_path)),
            "route_params": re.findall(r"\[([^\]]+)\]", str(rel_path)),
            **_HEALTH_DEFAULTS,
            "level": _calculate_level(display_path),
            "parent_path": _calculate_parent_path(display_path),
        },
    )


class PageScanner(BaseScanner):
    """Scans frontend pages for explorer entries (Next.js app router and SPAs)."""

    entry_type = "page"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self.frontend_dir: str = "frontend"
        self.frontend_port: int | None = None
        self.page_base_url: str | None = None

    def _load_config(self) -> bool:
        """Load root_path and frontend_dir from project config and overrides. Returns False on error."""
        project_config = get_project_config(self.project_id)
        if not project_config:
            logger.error(f"Project not found: {self.project_id}")
            return False
        for source in (project_config, self.config):
            if source.get("root_path"):
                self.root_path = Path(source["root_path"])
            if source.get("frontend_dir"):
                self.frontend_dir = source["frontend_dir"]
            if source.get("frontend_port"):
                try:
                    self.frontend_port = int(source["frontend_port"])
                except (ValueError, TypeError):
                    self.frontend_port = None
            if source.get("base_url"):
                self.page_base_url = str(source["base_url"]).rstrip("/")
        if not self.root_path:
            logger.error(f"No root_path for project {self.project_id}")
            return False
        if self.frontend_port is None:
            services = get_services(self.project_id)
            port = services.get("frontend_port")
            self.frontend_port = int(port) if isinstance(port, int) else None
            if not self.page_base_url and self.frontend_port is not None:
                self.page_base_url = f"http://localhost:{self.frontend_port}"
        return True

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan frontend pages and return page entries."""
        if not self._load_config():
            return []
        logger.info(f"Page scan started for {self.project_id}")
        entries = self._scan_nextjs_pages() or self._scan_spa_pages()
        logger.info(f"Page scan found {len(entries)} pages")
        return entries

    def _find_app_dir(self) -> Path | None:
        """Return the Next.js app directory, or None if not found."""
        if not self.root_path:
            return None
        for subpath in ("app", "src/app"):
            candidate = self.root_path / self.frontend_dir / subpath
            if candidate.exists():
                return candidate
        return None

    def _scan_nextjs_pages(self) -> list[ExplorerEntryCreate]:
        """Scan Next.js app router for frontend pages."""
        app_dir = self._find_app_dir()
        if not app_dir or not self.root_path:
            return []
        entries: list[ExplorerEntryCreate] = []
        for page_file in app_dir.rglob("page.tsx"):
            try:
                entries.append(
                    _build_nextjs_entry(
                        page_file,
                        app_dir,
                        self.root_path,
                        self.page_base_url,
                        self.frontend_port,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to scan page {page_file}: {e}")
        return entries

    def _scan_spa_pages(self) -> list[ExplorerEntryCreate]:
        """Scan for simple SPA projects with index.html at root."""
        if not self.root_path or not (self.root_path / "index.html").exists():
            return []
        return [
            ExplorerEntryCreate(
                path="/",
                name="home",
                health_status="unknown",
                metadata={
                    "method": "GET",
                    "port": self.frontend_port,
                    "url": f"{self.page_base_url}/" if self.page_base_url else None,
                    "source_file": "index.html",
                    "route_params": [],
                    **_HEALTH_DEFAULTS,
                    "level": 1,
                    "parent_path": None,
                    "spa": True,
                },
            )
        ]

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a page entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
