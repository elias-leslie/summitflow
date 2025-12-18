"""File scanner for Explorer.

Scans codebase files and produces entries for explorer_entries table.

Metadata schema (per architecture doc):
{
  "is_directory": true,
  "extension": ".py",
  "size_bytes": 1234,
  "lines_of_code": 456,
  "file_count": 10,
  "bloat_level": "warning",
  "stale_status": "fresh",
  "last_commit_days": 5,
  "last_commit_hash": "abc123",
  "last_commit_message": "feat: Add feature"
}
"""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

# Directories to skip during scan
SKIP_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git", ".next",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "data", "solution_state", ".beads",
}

# File extensions to skip
SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".mp3", ".mp4", ".wav", ".pdf",
    ".zip", ".tar", ".gz", ".lock",
}

# Bloat thresholds by extension: (warning_loc, critical_loc)
BLOAT_THRESHOLDS: dict[str, tuple[int, int]] = {
    ".py": (500, 1000),
    ".ts": (400, 800),
    ".tsx": (300, 600),
    ".js": (400, 800),
    ".jsx": (300, 600),
    ".sql": (200, 500),
    ".md": (500, 1000),
    ".css": (400, 800),
    ".scss": (400, 800),
}

STALE_THRESHOLD_DAYS = 90


class FileScanner(BaseScanner):
    """Scans codebase files for explorer entries."""

    entry_type = "file"

    def __init__(self, project_id: str, config: dict | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan codebase and return file entries."""
        # Get root path from project config
        root = get_project_root(self.project_id)
        if not root:
            logger.error(f"No root_path configured for project {self.project_id}")
            return []

        self.root_path = Path(root)
        if not self.root_path.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return []

        logger.info(f"File scan started for {self.project_id}: {self.root_path}")

        entries: list[ExplorerEntryCreate] = []
        dir_stats: dict[str, dict] = {}  # path -> {file_count, total_loc}

        # Walk directory tree
        for root_dir, dirnames, filenames in os.walk(self.root_path):
            # Skip excluded directories
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            rel_root = Path(root_dir).relative_to(self.root_path)

            for filename in filenames:
                file_path = Path(root_dir) / filename
                rel_path = str(rel_root / filename) if rel_root != Path(".") else filename

                # Skip by extension
                ext = file_path.suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue

                try:
                    entry = self._scan_file(file_path, rel_path, ext)
                    if entry:
                        entries.append(entry)
                        self._aggregate_to_parents(rel_path, entry, dir_stats)
                except Exception as e:
                    logger.warning(f"File scan error for {rel_path}: {e}")

        # Add git info in batch (more efficient)
        self._add_git_info_batch(entries)

        # Create directory entries
        dir_entries = self._create_directory_entries(dir_stats)
        entries.extend(dir_entries)

        logger.info(f"File scan found {len(entries)} entries ({len(entries) - len(dir_entries)} files, {len(dir_entries)} dirs)")
        return entries

    def _scan_file(self, file_path: Path, rel_path: str, ext: str) -> ExplorerEntryCreate | None:
        """Scan a single file and return entry."""
        try:
            stat = file_path.stat()
            size_bytes = stat.st_size

            # Count lines of code
            try:
                with file_path.open(encoding="utf-8", errors="ignore") as f:
                    lines = sum(1 for _ in f)
            except Exception:
                lines = 0

            # Calculate bloat level
            bloat_level = self._calculate_bloat(ext, lines)

            return ExplorerEntryCreate(
                path=rel_path,
                name=file_path.name,
                health_status="unknown",  # Will be set by get_health_status
                metadata={
                    "is_directory": False,
                    "extension": ext if ext else None,
                    "size_bytes": size_bytes,
                    "lines_of_code": lines,
                    "bloat_level": bloat_level,
                },
            )
        except Exception:
            return None

    def _calculate_bloat(self, ext: str, lines: int) -> str | None:
        """Calculate bloat level based on file type and LOC."""
        thresholds = BLOAT_THRESHOLDS.get(ext)
        if not thresholds:
            return None

        warning, critical = thresholds
        if lines >= critical:
            return "critical"
        if lines >= warning:
            return "warning"
        return None

    def _aggregate_to_parents(
        self, rel_path: str, entry: ExplorerEntryCreate, dir_stats: dict[str, dict]
    ) -> None:
        """Aggregate file stats to parent directories."""
        path_parts = Path(rel_path).parts[:-1]
        lines = entry.metadata.get("lines_of_code", 0)

        for i in range(len(path_parts)):
            dir_path = str(Path(*path_parts[: i + 1]))
            if dir_path not in dir_stats:
                dir_stats[dir_path] = {"file_count": 0, "total_loc": 0}
            dir_stats[dir_path]["file_count"] += 1
            dir_stats[dir_path]["total_loc"] += lines

    def _create_directory_entries(self, dir_stats: dict[str, dict]) -> list[ExplorerEntryCreate]:
        """Create entries for directories."""
        entries = []
        for path, stats in dir_stats.items():
            entries.append(
                ExplorerEntryCreate(
                    path=path,
                    name=Path(path).name,
                    health_status="healthy",
                    metadata={
                        "is_directory": True,
                        "file_count": stats["file_count"],
                        "total_loc": stats["total_loc"],
                    },
                )
            )
        return entries

    def _add_git_info_batch(self, entries: list[ExplorerEntryCreate]) -> None:
        """Add git commit info to file entries."""
        if not self.root_path:
            return

        now = datetime.now(UTC)

        for entry in entries:
            if entry.metadata.get("is_directory"):
                continue

            try:
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%at|%h|%s", "--follow", "--", entry.path],
                    cwd=str(self.root_path),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )

                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split("|", 2)
                    if len(parts) >= 1 and parts[0]:
                        timestamp = int(parts[0])
                        commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
                        entry.metadata["last_commit_days"] = (now - commit_time).days

                        # Determine stale status
                        days = entry.metadata["last_commit_days"]
                        if days >= STALE_THRESHOLD_DAYS:
                            entry.metadata["stale_status"] = "stale"
                        else:
                            entry.metadata["stale_status"] = "fresh"

                    if len(parts) >= 2:
                        entry.metadata["last_commit_hash"] = parts[1]
                    if len(parts) >= 3:
                        entry.metadata["last_commit_message"] = parts[2][:100]

            except (subprocess.TimeoutExpired, ValueError, OSError):
                entry.metadata["stale_status"] = "unknown"

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a file entry."""
        meta = entry.metadata

        # Directories are always healthy
        if meta.get("is_directory"):
            return "healthy"

        # Check bloat level
        bloat = meta.get("bloat_level")
        if bloat == "critical":
            return "error"
        if bloat == "warning":
            return "warning"

        # Check stale status
        stale = meta.get("stale_status")
        if stale == "stale":
            return "warning"

        return "healthy"
