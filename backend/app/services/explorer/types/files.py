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
  "last_commit_message": "feat: Add feature",
  "function_count": 10,
  "class_count": 2,
  "import_count": 5,
  "complexity_score": 7.5,
  "refactor_priority": "medium"
}
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..constants import SKIP_DIRS
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

# File extensions to skip
SKIP_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".lock",
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

# Schema version for metadata - increment when adding new fields
METADATA_SCHEMA_VERSION = 2

# Regex patterns for complexity metrics
FUNCTION_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*def\s+", re.MULTILINE),
    ".ts": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
    ".tsx": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
    ".js": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
    ".jsx": re.compile(r"function\s+\w+|=>\s*\{|\bconst\s+\w+\s*=\s*\(", re.MULTILINE),
}

CLASS_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*class\s+\w+", re.MULTILINE),
    ".ts": re.compile(r"class\s+\w+", re.MULTILINE),
    ".tsx": re.compile(r"class\s+\w+", re.MULTILINE),
    ".js": re.compile(r"class\s+\w+", re.MULTILINE),
    ".jsx": re.compile(r"class\s+\w+", re.MULTILINE),
}

IMPORT_PATTERNS: dict[str, re.Pattern[str]] = {
    ".py": re.compile(r"^\s*(import|from)\s+", re.MULTILINE),
    ".ts": re.compile(r"^\s*import\s+", re.MULTILINE),
    ".tsx": re.compile(r"^\s*import\s+", re.MULTILINE),
    ".js": re.compile(r"^\s*import\s+", re.MULTILINE),
    ".jsx": re.compile(r"^\s*import\s+", re.MULTILINE),
}

# Refactor priority thresholds
REFACTOR_HIGH_COMPLEXITY = 15
REFACTOR_HIGH_LINES = 500
REFACTOR_MEDIUM_COMPLEXITY = 10
REFACTOR_MEDIUM_LINES = 300


class FileScanner(BaseScanner):
    """Scans codebase files for explorer entries."""

    entry_type = "file"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
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
        dir_stats: dict[str, dict[str, Any]] = {}  # path -> {file_count, total_loc}

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

        logger.info(
            f"File scan found {len(entries)} entries ({len(entries) - len(dir_entries)} files, {len(dir_entries)} dirs)"
        )
        return entries

    def _scan_file(self, file_path: Path, rel_path: str, ext: str) -> ExplorerEntryCreate | None:
        """Scan a single file and return entry."""
        try:
            stat = file_path.stat()
            size_bytes = stat.st_size

            # Read file content for analysis
            content = ""
            lines = 0
            try:
                with file_path.open(encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    lines = content.count("\n") + (
                        1 if content and not content.endswith("\n") else 0
                    )
            except Exception:
                lines = 0

            # Calculate bloat level
            bloat_level = self._calculate_bloat(ext, lines)

            # Calculate complexity metrics
            function_count = self._count_matches(ext, FUNCTION_PATTERNS, content)
            class_count = self._count_matches(ext, CLASS_PATTERNS, content)
            import_count = self._count_matches(ext, IMPORT_PATTERNS, content)
            complexity_score = self._calculate_complexity_score(lines, function_count, class_count)
            refactor_priority = self._calculate_refactor_priority(complexity_score, lines)

            return ExplorerEntryCreate(
                path=rel_path,
                name=file_path.name,
                health_status="unknown",  # Will be set by get_health_status
                metadata={
                    "_schema_version": METADATA_SCHEMA_VERSION,
                    "is_directory": False,
                    "extension": ext if ext else None,
                    "size_bytes": size_bytes,
                    "lines_of_code": lines,
                    "bloat_level": bloat_level,
                    "function_count": function_count,
                    "class_count": class_count,
                    "import_count": import_count,
                    "complexity_score": complexity_score,
                    "refactor_priority": refactor_priority,
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

    def _count_matches(self, ext: str, patterns: dict[str, re.Pattern[str]], content: str) -> int:
        """Count regex matches for the given extension."""
        pattern = patterns.get(ext)
        if not pattern or not content:
            return 0
        return len(pattern.findall(content))

    def _calculate_complexity_score(
        self, lines: int, function_count: int, class_count: int
    ) -> float:
        """Calculate complexity score: lines/100 + funcs/10 + classes/5."""
        return round(lines / 100 + function_count / 10 + class_count / 5, 2)

    def _calculate_refactor_priority(self, complexity_score: float, lines: int) -> str:
        """Determine refactor priority based on complexity and lines."""
        if complexity_score > REFACTOR_HIGH_COMPLEXITY or lines > REFACTOR_HIGH_LINES:
            return "high"
        if complexity_score > REFACTOR_MEDIUM_COMPLEXITY or lines > REFACTOR_MEDIUM_LINES:
            return "medium"
        return "none"

    def _aggregate_to_parents(
        self, rel_path: str, entry: ExplorerEntryCreate, dir_stats: dict[str, dict[str, Any]]
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

    def _create_directory_entries(
        self, dir_stats: dict[str, dict[str, Any]]
    ) -> list[ExplorerEntryCreate]:
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
                # Get last commit info
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

                # Get commit count in last 90 days (churn metric)
                commit_count = self._get_commit_count(entry.path)
                entry.metadata["commit_count_90d"] = commit_count

                # Check if test file exists
                test_file_exists = self._has_test_file(entry.path, entry.name)
                entry.metadata["test_file_exists"] = test_file_exists

            except (subprocess.TimeoutExpired, ValueError, OSError):
                entry.metadata["stale_status"] = "unknown"

    def _get_commit_count(self, file_path: str) -> int:
        """Get number of commits to a file in the last 90 days."""
        if not self.root_path:
            return 0

        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--oneline",
                    "--since=90 days ago",
                    "--follow",
                    "--",
                    file_path,
                ],
                cwd=str(self.root_path),
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                return len([line for line in lines if line.strip()])
            return 0
        except (subprocess.TimeoutExpired, OSError):
            return 0

    def _has_test_file(self, file_path: str, file_name: str) -> bool:
        """Check if a test file exists for this source file."""
        if not self.root_path:
            return False

        # Get base name without extension
        stem = Path(file_name).stem
        ext = Path(file_name).suffix

        # Skip if file is already a test file
        if stem.startswith("test_") or stem.endswith("_test"):
            return True  # It IS a test file

        # Get directory of the source file
        file_dir = Path(file_path).parent

        # Test file patterns to check
        test_patterns = [
            f"test_{stem}{ext}",  # test_module.py
            f"{stem}_test{ext}",  # module_test.py
        ]

        # Directories to check for tests
        test_dirs = [
            file_dir,  # Same directory
            Path("tests") / file_dir,  # tests/app/module/
            Path("tests"),  # tests/test_module.py
            file_dir / "tests",  # app/tests/test_module.py
        ]

        for test_dir in test_dirs:
            for pattern in test_patterns:
                test_path = self.root_path / test_dir / pattern
                if test_path.exists():
                    return True

        return False

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
