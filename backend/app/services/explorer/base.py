"""Base scanner class for Explorer service.

Provides shared scanning logic:
- Abstract scan() method for type-specific implementations
- Shared save() method using storage layer
- Health status determination
- Project root path resolution
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ...logging_config import get_logger
from ...storage import explorer as storage
from .models import ExplorerEntryCreate, ScanResult

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class BaseScanner(ABC):
    """Base class for all explorer scanners.

    Each scanner type (file, table, task, endpoint) extends this class
    and implements the scan() method with type-specific logic.

    Attributes:
        entry_type: The type of entries this scanner produces
        project_id: The project being scanned
        config: Optional configuration dict
    """

    entry_type: str  # Must be set by subclass: 'file', 'table', 'task', 'endpoint'

    def __init__(self, project_id: str, config: dict | None = None) -> None:
        """Initialize the scanner.

        Args:
            project_id: Project ID to scan
            config: Optional configuration dict (type-specific)
        """
        self.project_id = project_id
        self.config = config or {}

    @abstractmethod
    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan and return entries.

        Type-specific implementation that discovers entries
        and returns them as ExplorerEntryCreate objects.

        Returns:
            List of entries found during scan
        """
        pass

    def save(self, entries: list[ExplorerEntryCreate]) -> int:
        """Save entries to database using storage layer.

        Args:
            entries: List of entries to save

        Returns:
            Number of entries saved
        """
        if not entries:
            return 0

        entry_dicts = [
            {
                "path": e.path,
                "name": e.name,
                "health_status": e.health_status,
                "metadata": e.metadata,
            }
            for e in entries
        ]

        return storage.upsert_entries(self.project_id, self.entry_type, entry_dicts)

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for an entry.

        Default implementation returns the entry's current health status.
        Subclasses can override for type-specific health logic.

        Args:
            entry: The entry to evaluate

        Returns:
            Health status: 'healthy', 'warning', 'error', or 'unknown'
        """
        return entry.health_status

    def run(self) -> ScanResult:
        """Execute the full scan workflow.

        1. Calls scan() to discover entries
        2. Determines health status for each
        3. Saves entries to database
        4. Cleans up stale entries no longer in codebase

        Returns:
            ScanResult with statistics
        """
        start_time = time.time()

        try:
            # Scan for entries
            entries = self.scan()

            # Update health status for each entry
            for entry in entries:
                entry.health_status = self.get_health_status(entry)

            # Save to database
            saved_count = self.save(entries)

            # Clean up stale entries (entries in DB that weren't in this scan)
            current_paths = {e.path for e in entries}
            deleted_count = storage.cleanup_stale_entries(
                self.project_id, self.entry_type, current_paths
            )
            if deleted_count > 0:
                logger.info(
                    f"Cleaned up {deleted_count} stale {self.entry_type} entries "
                    f"for {self.project_id}"
                )

            duration_ms = int((time.time() - start_time) * 1000)

            logger.info(
                f"Scan complete: {self.entry_type} for {self.project_id} - "
                f"found {len(entries)}, saved {saved_count}, "
                f"deleted {deleted_count} stale in {duration_ms}ms"
            )

            return ScanResult(
                success=True,
                entry_type=self.entry_type,
                entries_found=len(entries),
                entries_saved=saved_count,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Scan failed: {self.entry_type} for {self.project_id} - {e}")

            return ScanResult(
                success=False,
                entry_type=self.entry_type,
                entries_found=0,
                entries_saved=0,
                duration_ms=duration_ms,
                error=str(e),
            )


def get_project_root(project_id: str) -> str | None:
    """Get the root path for a project from database.

    Args:
        project_id: Project ID to look up

    Returns:
        Root path or None if not found
    """
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def get_project_config(project_id: str) -> dict | None:
    """Get full project configuration from database.

    Args:
        project_id: Project ID to look up

    Returns:
        Project config dict or None if not found
    """
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, base_url, health_endpoint, frontend_port, backend_port,
                   root_path, backend_dir, browser_scripts_dir, data_dir
            FROM projects WHERE id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "name": row[1],
            "base_url": row[2],
            "health_endpoint": row[3],
            "frontend_port": row[4],
            "backend_port": row[5],
            "root_path": row[6],
            "backend_dir": row[7],
            "browser_scripts_dir": row[8],
            "data_dir": row[9],
        }
