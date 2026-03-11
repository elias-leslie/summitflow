"""Dependency scanner for Explorer.

Scans Python (pyproject.toml, uv.lock) and Node.js (package.json, pnpm-lock.yaml)
dependencies across the monorepo. Includes security audit and outdated checks.

Metadata schema:
{
  "package_type": "python" | "nodejs",
  "constraint": ">=1.0.0",
  "locked_version": "1.2.3",
  "latest_version": "1.5.0",
  "is_outdated": true,
  "is_workspace_ref": false,
  "is_dev_dependency": false,
  "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
  "audit_advisories": ["CVE-2024-XXXX: Description..."],
  "source_file": "/path/to/pyproject.toml"
}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .dependencies_nodejs import scan_nodejs_dependencies
from .dependencies_python import scan_python_dependencies

logger = get_logger(__name__)


class DependencyScanner(BaseScanner):
    """Scans project dependencies for explorer entries."""

    entry_type = "dependency"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan dependencies and return entries."""
        root = get_project_root(self.project_id)
        if not root:
            logger.error("No root_path configured for project %s", self.project_id)
            return []

        self.root_path = Path(root)
        if not self.root_path.exists():
            logger.error("Root path does not exist: %s", self.root_path)
            return []

        logger.info("Dependency scan started for %s: %s", self.project_id, self.root_path)

        entries: list[ExplorerEntryCreate] = []

        # Scan Python dependencies
        python_entries = scan_python_dependencies(self.project_id, self.root_path)
        entries.extend(python_entries)

        # Scan Node.js dependencies
        node_entries = scan_nodejs_dependencies(self.project_id, self.root_path)
        entries.extend(node_entries)

        logger.info(
            "Dependency scan found %d entries (%d Python, %d Node.js)",
            len(entries), len(python_entries), len(node_entries),
        )
        return entries

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a dependency entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
