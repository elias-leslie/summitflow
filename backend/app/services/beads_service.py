"""Beads service - wrapper for bd CLI.

This service provides a Python interface to the beads CLI for issue tracking.
Beads stay in project .beads/ directory (JSONL), NOT in PostgreSQL.
SummitFlow provides VIEW + CRUD via bd CLI subprocess calls.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.logging_config import get_logger

logger = get_logger(__name__)

# bd CLI path - check user's bin first, then fallback to PATH
BD_PATH = os.environ.get("BD_PATH", str(Path.home() / "bin" / "bd"))
if not Path(BD_PATH).exists():
    BD_PATH = "bd"  # Fallback to PATH lookup


@dataclass
class BeadResult:
    """Result of a bead operation."""

    success: bool
    data: Any | None = None
    error: str | None = None


class BeadsService:
    """Service for interacting with beads via bd CLI."""

    def __init__(self, project_path: str) -> None:
        """Initialize beads service.

        Args:
            project_path: Path to the project root containing .beads/ directory
        """
        self.project_path = Path(project_path)
        self.beads_dir = self.project_path / ".beads"

    def _run_bd(
        self, args: list[str], timeout: int = 30, capture_json: bool = True
    ) -> BeadResult:
        """Run a bd command and return the result.

        Args:
            args: Arguments to pass to bd command
            timeout: Timeout in seconds
            capture_json: Whether to expect JSON output

        Returns:
            BeadResult with success status and data/error
        """
        cmd = [BD_PATH, *args]
        if capture_json and "--json" not in args:
            cmd.append("--json")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                logger.warning("bd command failed", cmd=cmd, error=error_msg)
                return BeadResult(success=False, error=error_msg)

            if capture_json:
                try:
                    data = json.loads(result.stdout)
                    return BeadResult(success=True, data=data)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse bd JSON output", error=str(e))
                    return BeadResult(success=False, error=f"JSON parse error: {e}")
            else:
                return BeadResult(success=True, data=result.stdout.strip())

        except subprocess.TimeoutExpired:
            logger.error("bd command timed out", cmd=cmd)
            return BeadResult(success=False, error="Command timed out")
        except Exception as e:
            logger.error("bd command failed", cmd=cmd, error=str(e))
            return BeadResult(success=False, error=str(e))

    def has_beads(self) -> bool:
        """Check if project has a .beads directory."""
        return self.beads_dir.exists()

    def list_beads(
        self,
        status: Literal["all", "open", "closed"] | None = None,
        limit: int = 100,
    ) -> BeadResult:
        """List beads for the project.

        Args:
            status: Filter by status (all, open, closed)
            limit: Maximum number of beads to return

        Returns:
            BeadResult with list of beads
        """
        args = ["list", f"--limit={limit}"]
        if status and status != "all":
            args.append(f"--status={status}")
        return self._run_bd(args)

    def get_ready(self) -> BeadResult:
        """Get beads ready for work (no blockers).

        Returns:
            BeadResult with list of ready beads
        """
        return self._run_bd(["ready"])

    def get_bead(self, bead_id: str) -> BeadResult:
        """Get a single bead by ID.

        Args:
            bead_id: The bead ID

        Returns:
            BeadResult with bead data
        """
        result = self._run_bd(["show", bead_id])
        # bd show returns an array, extract first item
        if result.success and isinstance(result.data, list) and len(result.data) > 0:
            result.data = result.data[0]
        return result

    def create_bead(
        self,
        title: str,
        description: str | None = None,
        priority: int = 2,
        issue_type: str = "task",
        labels: list[str] | None = None,
    ) -> BeadResult:
        """Create a new bead.

        Args:
            title: Bead title
            description: Bead description
            priority: Priority level (0-4)
            issue_type: Type (task, bug, feature, epic)
            labels: Optional labels

        Returns:
            BeadResult with created bead data
        """
        args = ["create", title, f"-p={priority}", f"-t={issue_type}"]

        if description:
            args.extend(["-d", description])

        if labels:
            for label in labels:
                args.extend(["--set-labels", label])

        return self._run_bd(args)

    def update_bead(
        self,
        bead_id: str,
        status: str | None = None,
        priority: int | None = None,
        title: str | None = None,
        notes: str | None = None,
        labels: list[str] | None = None,
    ) -> BeadResult:
        """Update an existing bead.

        Args:
            bead_id: The bead ID
            status: New status (open, in_progress, closed)
            priority: New priority (0-4)
            title: New title
            notes: Notes to add
            labels: Labels to set

        Returns:
            BeadResult with updated bead data
        """
        args = ["update", bead_id]

        if status:
            args.extend(["--status", status])
        if priority is not None:
            args.extend(["-p", str(priority)])
        if title:
            args.extend(["--title", title])
        if notes:
            args.extend(["--notes", notes])
        if labels:
            for label in labels:
                args.extend(["--set-labels", label])

        return self._run_bd(args)

    def close_bead(self, bead_id: str, reason: str) -> BeadResult:
        """Close a bead with a reason.

        Args:
            bead_id: The bead ID
            reason: Closure reason

        Returns:
            BeadResult with closed bead data
        """
        return self._run_bd(["close", bead_id, "--reason", reason])

    def get_stats(self) -> dict[str, Any]:
        """Get bead statistics for the project.

        Returns:
            Dict with counts by status and priority
        """
        result = self.list_beads(status="all", limit=1000)
        if not result.success or not result.data:
            return {"total": 0, "open": 0, "closed": 0, "in_progress": 0}

        beads = result.data
        stats = {
            "total": len(beads),
            "open": sum(1 for b in beads if b.get("status") == "open"),
            "closed": sum(1 for b in beads if b.get("status") == "closed"),
            "in_progress": sum(1 for b in beads if b.get("status") == "in_progress"),
            "by_priority": {},
            "by_type": {},
        }

        for bead in beads:
            if bead.get("status") != "closed":
                priority = bead.get("priority", 2)
                stats["by_priority"][priority] = stats["by_priority"].get(priority, 0) + 1

                issue_type = bead.get("issue_type", "task")
                stats["by_type"][issue_type] = stats["by_type"].get(issue_type, 0) + 1

        return stats
