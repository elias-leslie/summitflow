"""File scanner for Explorer.

Scans codebase files and produces entries for explorer_entries table.
See architecture doc for full metadata schema.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..constants import SKIP_DIRS
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .file_analysis import calculate_basic_metrics, calculate_bloat, read_file_content
from .file_constants import SKIP_EXTENSIONS
from .file_detection import compute_health_flags, detect_compat_cruft, detect_magic_strings
from .file_git import apply_git_info_to_entry, get_all_commit_counts_90d, get_all_last_commits
from .file_scan_helpers import (
    build_file_metadata,
    compute_file_complexity,
    compute_refactor_fields,
)
from .file_utils import aggregate_to_parents, create_directory_entries, has_test_file

logger = get_logger(__name__)


class FileScanner(BaseScanner):
    """Scans codebase files for explorer entries."""

    entry_type = "file"

    def __init__(self, project_id: str, config: dict[str, object] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan codebase and return file entries."""
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
        dir_stats: dict[str, dict[str, int]] = {}

        for root_dir, dirnames, filenames in os.walk(self.root_path):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            rel_root = Path(root_dir).relative_to(self.root_path)

            for filename in filenames:
                file_path = Path(root_dir) / filename
                rel_path = str(rel_root / filename) if rel_root != Path(".") else filename
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

        self._add_git_info_batch(entries)
        dir_entries = create_directory_entries(dir_stats)
        entries.extend(dir_entries)

        logger.info(
            f"File scan found {len(entries)} entries "
            f"({len(entries) - len(dir_entries)} files, {len(dir_entries)} dirs)"
        )
        return entries

    def _scan_file(self, file_path: Path, rel_path: str, ext: str) -> ExplorerEntryCreate | None:
        """Scan a single file and return entry."""
        try:
            size_bytes = file_path.stat().st_size
            content, lines = read_file_content(file_path)
            bloat_level = calculate_bloat(ext, lines)
            function_count, class_count, import_count = calculate_basic_metrics(ext, content)
            complexity = compute_file_complexity(ext, content, lines, function_count, class_count)
            magic_strings = detect_magic_strings(rel_path, content)
            compat_cruft = detect_compat_cruft(rel_path, content)
            health_flags = compute_health_flags(file_path, ext, function_count, class_count, import_count)
            refactor_priority, refactor_issues = compute_refactor_fields(
                complexity, lines, health_flags, bloat_level, magic_strings, compat_cruft
            )
            return ExplorerEntryCreate(
                path=rel_path,
                name=file_path.name,
                health_status="unknown",
                metadata=build_file_metadata(
                    ext, size_bytes, lines, bloat_level,
                    function_count, class_count, import_count,
                    complexity, refactor_priority, refactor_issues,
                    magic_strings, compat_cruft, health_flags,
                ),
            )
        except Exception:
            logger.debug("Failed to scan file: %s", rel_path, exc_info=True)
            return None

    def _add_git_info_batch(self, entries: list[ExplorerEntryCreate]) -> None:
        """Add git commit info to file entries using batch git operations."""
        if not self.root_path:
            return

        now = datetime.now(UTC)
        file_paths = {entry.path for entry in entries if not entry.metadata.get("is_directory")}
        if not file_paths:
            return

        last_commit_map = get_all_last_commits(self.root_path)
        commit_count_map = get_all_commit_counts_90d(self.root_path)

        for entry in entries:
            if entry.metadata.get("is_directory"):
                continue
            apply_git_info_to_entry(entry.metadata, entry.path, last_commit_map, commit_count_map, now)
            entry.metadata["test_file_exists"] = has_test_file(self.root_path, entry.path, entry.name)

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for a file entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
