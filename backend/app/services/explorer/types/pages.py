"""Page scanner for Explorer.

Scans frontend pages, producing entries for explorer_entries table.
Supports:
- Next.js app router (page.tsx files in app/ or src/app/)
- Simple SPAs (index.html at project root)

Metadata schema (per architecture doc):
{
  "method": "GET",
  "port": 3001,
  "source_file": "app/projects/[id]/page.tsx",
  "route_params": ["id"],
  "http_status": 200,
  "response_time_ms": 45,
  "console_errors": 0,
  "console_warnings": 0,
  "last_health_check": "2025-12-18T10:30:00Z"
}
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_config
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)


class PageScanner(BaseScanner):
    """Scans frontend pages for explorer entries.

    Supports Next.js app router and simple SPA projects.
    """

    entry_type = "page"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self.frontend_dir: str = "frontend"

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan frontend pages and return page entries."""
        # Get project config
        project_config = get_project_config(self.project_id)
        if not project_config:
            logger.error(f"Project not found: {self.project_id}")
            return []

        if project_config.get("root_path"):
            self.root_path = Path(project_config["root_path"])
        if project_config.get("frontend_dir"):
            self.frontend_dir = project_config["frontend_dir"]

        # Check config overrides
        if self.config:
            if self.config.get("root_path"):
                self.root_path = Path(self.config["root_path"])
            if self.config.get("frontend_dir"):
                self.frontend_dir = self.config["frontend_dir"]

        if not self.root_path:
            logger.error(f"No root_path for project {self.project_id}")
            return []

        logger.info(f"Page scan started for {self.project_id}")

        # Try Next.js app router first
        entries = self._scan_nextjs_pages()

        # Fall back to simple SPA detection if no Next.js pages found
        if not entries:
            entries = self._scan_spa_pages()

        logger.info(f"Page scan found {len(entries)} pages")
        return entries

    def _scan_nextjs_pages(self) -> list[ExplorerEntryCreate]:
        """Scan Next.js app router for frontend pages."""
        entries: list[ExplorerEntryCreate] = []

        if not self.root_path:
            return entries

        # Try standard location first, then src subdirectory (common in some Next.js projects)
        app_dir = self.root_path / self.frontend_dir / "app"
        if not app_dir.exists():
            app_dir = self.root_path / self.frontend_dir / "src" / "app"
        if not app_dir.exists():
            return entries

        # Find all page.tsx files in app directory
        for page_file in app_dir.rglob("page.tsx"):
            try:
                # Extract route path from file location
                rel_path = page_file.parent.relative_to(app_dir)
                route_path = "/" + str(rel_path).replace("\\", "/")

                # Extract route params (e.g., [id] -> id)
                route_params = re.findall(r"\[([^\]]+)\]", str(rel_path))

                # Clean up Next.js route syntax for display
                display_path = re.sub(r"\[([^\]]+)\]", r":\1", route_path)  # [id] -> :id
                display_path = display_path.replace("/(", "/").replace(
                    ")/", "/"
                )  # Remove route groups
                if display_path == "/.":
                    display_path = "/"

                # Determine page name
                page_name = page_file.parent.name
                if page_name.startswith("[") and page_name.endswith("]"):
                    # Dynamic route - use parent directory name
                    parent_name = page_file.parent.parent.name
                    page_name = f"{parent_name}/:{page_name[1:-1]}"
                if not page_name or page_name == ".":
                    page_name = "home"

                # Calculate hierarchy metadata
                level = _calculate_level(display_path)
                parent_path = _calculate_parent_path(display_path)

                entries.append(
                    ExplorerEntryCreate(
                        path=display_path,
                        name=page_name,
                        health_status="unknown",
                        metadata={
                            "method": "GET",
                            "port": 3001,
                            "source_file": str(page_file.relative_to(self.root_path))
                            if self.root_path
                            else "unknown",
                            "route_params": route_params,
                            "http_status": None,
                            "response_time_ms": None,
                            "console_errors": None,
                            "console_warnings": None,
                            "last_health_check": None,
                            "level": level,
                            "parent_path": parent_path,
                        },
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to scan page {page_file}: {e}")

        return entries

    def _scan_spa_pages(self) -> list[ExplorerEntryCreate]:
        """Scan for simple SPA projects with index.html at root."""
        entries: list[ExplorerEntryCreate] = []

        if not self.root_path:
            return entries

        # Check for index.html at project root (simple SPA like games, static sites)
        index_file = self.root_path / "index.html"
        if index_file.exists():
            entries.append(
                ExplorerEntryCreate(
                    path="/",
                    name="home",
                    health_status="unknown",
                    metadata={
                        "method": "GET",
                        "port": 3001,
                        "source_file": "index.html",
                        "route_params": [],
                        "http_status": None,
                        "response_time_ms": None,
                        "console_errors": None,
                        "console_warnings": None,
                        "last_health_check": None,
                        "level": 1,
                        "parent_path": None,
                        "spa": True,
                    },
                )
            )

        return entries

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a page entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)


def _calculate_level(path: str) -> int:
    """Calculate hierarchy level from path.

    Level is determined by path depth:
    - / = level 1 (app root)
    - /projects, /settings = level 2 (sections)
    - /projects/:id = level 3 (detail)
    - /projects/:id/settings = level 4 (sub-detail)

    Args:
        path: Route path (e.g., "/projects/:id/settings")

    Returns:
        Hierarchy level (1-based)
    """
    if path == "/":
        return 1

    # Split by "/" and filter empty segments
    segments = [s for s in path.split("/") if s]
    return len(segments) + 1


def _calculate_parent_path(path: str) -> str | None:
    """Calculate parent path for hierarchy.

    Args:
        path: Route path (e.g., "/projects/:id/settings")

    Returns:
        Parent path (e.g., "/projects/:id") or None for root
    """
    if path == "/":
        return None

    # Split and remove last segment
    segments = [s for s in path.split("/") if s]
    if len(segments) <= 1:
        return "/"

    return "/" + "/".join(segments[:-1])
