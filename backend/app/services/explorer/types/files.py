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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..constants import SKIP_DIRS
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .file_analysis import calculate_basic_metrics, calculate_bloat, read_file_content
from .file_complexity import (
    analyze_python_complexity,
    build_refactor_issues,
    calculate_complexity_score,
    calculate_refactor_priority,
)
from .file_constants import METADATA_SCHEMA_VERSION, SKIP_EXTENSIONS
from .file_detection import compute_health_flags, detect_compat_cruft, detect_magic_strings
from .file_git import apply_git_info_to_entry, get_all_commit_counts_90d, get_all_last_commits
from .file_utils import aggregate_to_parents, create_directory_entries, has_test_file

logger = get_logger(__name__)


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
                        aggregate_to_parents(rel_path, entry, dir_stats)
                except Exception as e:
                    logger.warning(f"File scan error for {rel_path}: {e}")

        # Add git info in batch (more efficient)
        self._add_git_info_batch(entries)

        # Create directory entries
        dir_entries = create_directory_entries(dir_stats)
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
            content, lines = read_file_content(file_path)

            # Calculate bloat level
            bloat_level = calculate_bloat(ext, lines)

            # Calculate complexity metrics
            function_count, class_count, import_count = calculate_basic_metrics(ext, content)

            # Calculate complexity score and method
            if ext == ".py" and content:
                complexity_score, complexity_method, cc_avg, cc_max, comment_density = (
                    analyze_python_complexity(content, lines, function_count, class_count)
                )
            else:
                complexity_score = calculate_complexity_score(lines, function_count, class_count)
                complexity_method = "heuristic"
                cc_avg = None
                cc_max = None
                comment_density = None

            # Detect magic strings
            magic_strings = detect_magic_strings(rel_path, content)

            # Detect compat cruft
            compat_cruft = detect_compat_cruft(rel_path, content)

            # Compute health flags from thresholds
            health_flags = compute_health_flags(
                file_path, ext, function_count, class_count, import_count
            )

            # Priority considers ALL issue dimensions, not just complexity/LOC
            refactor_priority = calculate_refactor_priority(
                complexity_score, lines,
                health_flags=health_flags or None,
                bloat_level=bloat_level,
            )

            # Build explicit list of all issues found
            refactor_issues = build_refactor_issues(
                complexity_score, lines,
                health_flags=health_flags or None,
                bloat_level=bloat_level,
                magic_strings=magic_strings or None,
                compat_cruft=compat_cruft or None,
            )

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
                    "complexity_method": complexity_method,
                    "cyclomatic_complexity_avg": cc_avg,
                    "cyclomatic_complexity_max": cc_max,
                    "comment_density": comment_density,
                    "refactor_priority": refactor_priority,
                    "refactor_issues": refactor_issues if refactor_issues else None,
                    "magic_strings": magic_strings if magic_strings else None,
                    "compat_cruft": compat_cruft if compat_cruft else None,
                    "health_flags": health_flags if health_flags else None,
                },
            )
        except Exception:
            logger.debug("Failed to scan file: %s", rel_path, exc_info=True)
            return None

    def _add_git_info_batch(self, entries: list[ExplorerEntryCreate]) -> None:
        """Add git commit info to file entries using batch git operations.

        Optimized to use only 2 git calls total instead of 2 per file.
        For 25k files, this reduces git calls from 50k to 2.
        """
        if not self.root_path:
            return

        now = datetime.now(UTC)

        # Build set of file paths for quick lookup
        file_paths = {entry.path for entry in entries if not entry.metadata.get("is_directory")}
        if not file_paths:
            return

        # Batch 1: Get last commit info for ALL files (single git call)
        last_commit_map = get_all_last_commits(self.root_path)

        # Batch 2: Get 90-day commit counts for ALL files (single git call)
        commit_count_map = get_all_commit_counts_90d(self.root_path)

        # Apply git info to entries
        for entry in entries:
            if entry.metadata.get("is_directory"):
                continue

            apply_git_info_to_entry(
                entry.metadata, entry.path, last_commit_map, commit_count_map, now
            )

            # Check if test file exists (filesystem check - fast)
            entry.metadata["test_file_exists"] = has_test_file(
                self.root_path, entry.path, entry.name
            )

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a file entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
