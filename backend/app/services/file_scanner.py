"""File scanner for codebase complexity audit.

Central scanning service that can scan any registered project's codebase.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..storage.connection import get_connection

logger = logging.getLogger(__name__)

# Stale detection thresholds (days since last git commit)
STALE_THRESHOLD_DAYS = 90  # Files older than this are "stale"
ORPHAN_MIN_DAYS = 30  # Orphans must be at least this old (avoid false positives)

# Directories to skip during scan
SKIP_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "data",
    "solution_state",
    ".beads",
}

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


@dataclass
class FileStats:
    """Statistics for a single file or directory."""

    path: str
    is_directory: bool
    extension: str | None
    size_bytes: int
    lines_of_code: int
    file_count: int | None  # Only for directories
    total_loc: int | None  # Only for directories
    bloat_level: str | None  # null, 'warning', 'critical'
    last_modified: datetime
    # Stale detection fields
    last_commit_days: int | None = None  # Days since last git commit
    reference_count: int = 0  # Number of files referencing this file
    stale_status: str | None = None  # 'fresh', 'stale', 'orphan'


class FileScanner:
    """Scans codebase and produces file audit metrics."""

    def __init__(self, project_id: str, root_path: str) -> None:
        self.project_id = project_id
        self.root_path = Path(root_path)

    def scan(self) -> dict[str, Any]:
        """Scan the codebase and store results in database."""
        logger.info(f"File scan started for {self.project_id}: {self.root_path}")

        files: list[FileStats] = []
        dirs: dict[str, dict[str, Any]] = {}  # path -> {file_count, total_loc}

        for root, dirnames, filenames in os.walk(self.root_path):
            # Skip excluded directories
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            rel_root = Path(root).relative_to(self.root_path)

            for filename in filenames:
                file_path = Path(root) / filename
                rel_path = str(rel_root / filename)

                # Skip by extension
                ext = file_path.suffix.lower()
                if ext in SKIP_EXTENSIONS:
                    continue

                try:
                    stats = self._get_file_stats(file_path, rel_path, ext)
                    if stats:
                        files.append(stats)
                        self._aggregate_to_parents(rel_path, stats, dirs)
                except Exception as e:
                    logger.warning(f"File scan error for {rel_path}: {e}")

        # Add stale detection: git commit age and reference tracking
        logger.info(f"Starting stale detection for {len(files)} files")
        self._add_git_commit_ages(files)
        self._add_reference_counts(files)
        self._calculate_stale_statuses(files)

        # Convert directory aggregates to FileStats
        dir_stats = self._finalize_directories(dirs)

        # Store in database
        self._store_results(files, dir_stats)

        summary = {
            "total_files": len(files),
            "total_directories": len(dir_stats),
            "total_loc": sum(f.lines_of_code for f in files),
            "bloat_warnings": sum(1 for f in files if f.bloat_level == "warning"),
            "bloat_critical": sum(1 for f in files if f.bloat_level == "critical"),
            "stale_files": sum(1 for f in files if f.stale_status == "stale"),
            "orphan_files": sum(1 for f in files if f.stale_status == "orphan"),
            "untracked_files": sum(1 for f in files if f.stale_status == "untracked"),
            "scanned_at": datetime.now(UTC).isoformat(),
        }

        logger.info(f"File scan completed: {summary}")
        return summary

    def _get_file_stats(self, file_path: Path, rel_path: str, ext: str) -> FileStats | None:
        """Get statistics for a single file."""
        try:
            stat = file_path.stat()
            size_bytes = stat.st_size
            last_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

            # Count lines of code
            try:
                with file_path.open(encoding="utf-8", errors="ignore") as f:
                    lines = sum(1 for _ in f)
            except Exception:
                lines = 0

            # Determine bloat level
            bloat_level = self._calculate_bloat(ext, lines)

            return FileStats(
                path=rel_path,
                is_directory=False,
                extension=ext if ext else None,
                size_bytes=size_bytes,
                lines_of_code=lines,
                file_count=None,
                total_loc=None,
                bloat_level=bloat_level,
                last_modified=last_modified,
            )
        except Exception:
            return None

    def _calculate_bloat(self, ext: str, lines: int) -> str | None:
        """Calculate bloat level based on file type and line count."""
        thresholds = BLOAT_THRESHOLDS.get(ext)
        if not thresholds:
            return None

        warning, critical = thresholds
        if lines >= critical:
            return "critical"
        if lines >= warning:
            return "warning"
        return None

    def _add_git_commit_ages(self, files: list[FileStats]) -> None:
        """Add git commit age (days) to each file."""
        now = datetime.now(UTC)
        for stats in files:
            try:
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%at", "--follow", "--", stats.path],
                    cwd=str(self.root_path),
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip():
                    timestamp = int(result.stdout.strip())
                    commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
                    stats.last_commit_days = (now - commit_time).days
                else:
                    stats.last_commit_days = None
            except (subprocess.TimeoutExpired, ValueError, OSError):
                stats.last_commit_days = None

    def _add_reference_counts(self, files: list[FileStats]) -> None:
        """Count how many other files reference each file."""
        source_exts = {".py", ".ts", ".tsx", ".js", ".jsx"}
        source_files = [f for f in files if f.extension in source_exts]

        for target in source_files:
            stem = Path(target.path).stem
            ref_count = 0

            for source in source_files:
                if source.path == target.path:
                    continue

                try:
                    full_path = self.root_path / source.path
                    with full_path.open(encoding="utf-8", errors="ignore") as f:
                        content = f.read()

                    patterns = [
                        rf"from\s+['\"].*{re.escape(stem)}['\"]",
                        rf"import\s+['\"].*{re.escape(stem)}['\"]",
                        rf"import\s+.*\s+from\s+['\"].*{re.escape(stem)}['\"]",
                        rf"require\s*\(\s*['\"].*{re.escape(stem)}['\"]",
                        rf"from\s+\..*{re.escape(stem)}\s+import",
                    ]

                    for pattern in patterns:
                        if re.search(pattern, content, re.IGNORECASE):
                            ref_count += 1
                            break
                except OSError:
                    continue

            target.reference_count = ref_count

    def _calculate_stale_statuses(self, files: list[FileStats]) -> None:
        """Calculate stale status for each file based on commit age and references."""
        for stats in files:
            if stats.is_directory:
                stats.stale_status = None
                continue

            days = stats.last_commit_days
            refs = stats.reference_count

            if days is None:
                if refs == 0:
                    stats.stale_status = "untracked"
                else:
                    stats.stale_status = "fresh"
            elif days >= STALE_THRESHOLD_DAYS and refs == 0 and days >= ORPHAN_MIN_DAYS:
                stats.stale_status = "orphan"
            elif days >= STALE_THRESHOLD_DAYS:
                stats.stale_status = "stale"
            else:
                stats.stale_status = "fresh"

    def _aggregate_to_parents(
        self, rel_path: str, stats: FileStats, dirs: dict[str, dict[str, Any]]
    ) -> None:
        """Aggregate file stats to all parent directories."""
        path_parts = Path(rel_path).parts[:-1]

        for i in range(len(path_parts)):
            dir_path = str(Path(*path_parts[: i + 1]))
            if dir_path not in dirs:
                dirs[dir_path] = {"file_count": 0, "total_loc": 0, "total_size": 0}
            dirs[dir_path]["file_count"] += 1
            dirs[dir_path]["total_loc"] += stats.lines_of_code
            dirs[dir_path]["total_size"] += stats.size_bytes

    def _finalize_directories(self, dirs: dict[str, dict[str, Any]]) -> list[FileStats]:
        """Convert directory aggregates to FileStats."""
        result = []
        now = datetime.now(UTC)

        for dir_path, data in dirs.items():
            result.append(
                FileStats(
                    path=dir_path,
                    is_directory=True,
                    extension=None,
                    size_bytes=data.get("total_size", 0),
                    lines_of_code=0,
                    file_count=data["file_count"],
                    total_loc=data["total_loc"],
                    bloat_level=None,
                    last_modified=now,
                )
            )

        return result

    def _store_results(self, files: list[FileStats], directories: list[FileStats]) -> None:
        """Store scan results in database."""
        all_stats = files + directories

        with get_connection() as conn:
            with conn.cursor() as cur:
                # Clear existing data for this project
                cur.execute("DELETE FROM file_audit WHERE project_id = %s", (self.project_id,))

                # Insert new data
                for stat in all_stats:
                    cur.execute(
                        """
                        INSERT INTO file_audit (
                            project_id, path, is_directory, extension, size_bytes,
                            lines_of_code, file_count, total_loc, bloat_level,
                            last_modified, last_commit_days, reference_count,
                            stale_status, scanned_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            self.project_id,
                            stat.path,
                            stat.is_directory,
                            stat.extension,
                            stat.size_bytes,
                            stat.lines_of_code,
                            stat.file_count,
                            stat.total_loc,
                            stat.bloat_level,
                            stat.last_modified,
                            stat.last_commit_days,
                            stat.reference_count,
                            stat.stale_status,
                        ),
                    )
                conn.commit()

        logger.info(f"Stored {len(files)} files and {len(directories)} directories for {self.project_id}")


def get_summary(project_id: str) -> dict[str, Any]:
    """Get summary statistics from stored audit data."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE NOT is_directory) as total_files,
                    COUNT(*) FILTER (WHERE is_directory) as total_directories,
                    SUM(lines_of_code) FILTER (WHERE NOT is_directory) as total_loc,
                    COUNT(*) FILTER (WHERE bloat_level = 'warning') as bloat_warnings,
                    COUNT(*) FILTER (WHERE bloat_level = 'critical') as bloat_critical,
                    MAX(scanned_at) as last_scan,
                    COUNT(*) FILTER (WHERE stale_status = 'stale') as stale_files,
                    COUNT(*) FILTER (WHERE stale_status = 'orphan') as orphan_files,
                    COUNT(*) FILTER (WHERE stale_status = 'untracked') as untracked_files
                FROM file_audit
                WHERE project_id = %s
                """,
                (project_id,),
            )
            row = cur.fetchone()

    if not row or row[0] is None:
        return {
            "total_files": 0,
            "total_directories": 0,
            "total_loc": 0,
            "bloat_warnings": 0,
            "bloat_critical": 0,
            "last_scan": None,
            "stale_files": 0,
            "orphan_files": 0,
            "untracked_files": 0,
        }

    return {
        "total_files": row[0] or 0,
        "total_directories": row[1] or 0,
        "total_loc": row[2] or 0,
        "bloat_warnings": row[3] or 0,
        "bloat_critical": row[4] or 0,
        "last_scan": row[5].isoformat() if row[5] else None,
        "stale_files": row[6] or 0,
        "orphan_files": row[7] or 0,
        "untracked_files": row[8] or 0,
    }


def get_children(
    project_id: str,
    path: str = "",
    sort: str = "name",
    direction: str = "asc",
    folders_first: bool = True,
    include_files: bool = True,
) -> list[dict[str, Any]]:
    """Get immediate children of a path."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Build query for immediate children
            if path:
                # Children of a specific path
                pattern = f"{path}/%"
                # Exclude deeper nested paths
                exclude_pattern = f"{path}/%/%"
            else:
                # Root level items
                pattern = "%"
                exclude_pattern = "%/%"

            cur.execute(
                """
                SELECT
                    path, is_directory, extension, size_bytes, lines_of_code,
                    file_count, total_loc, bloat_level, last_modified,
                    last_commit_days, reference_count, stale_status
                FROM file_audit
                WHERE project_id = %s
                  AND path LIKE %s
                  AND path NOT LIKE %s
                ORDER BY is_directory DESC, path ASC
                """,
                (project_id, pattern, exclude_pattern),
            )
            rows = cur.fetchall()

    results = []
    for row in rows:
        item = {
            "path": row[0],
            "name": Path(row[0]).name,
            "is_directory": row[1],
            "extension": row[2],
            "size_bytes": row[3],
            "lines_of_code": row[4],
            "file_count": row[5],
            "total_loc": row[6],
            "bloat_level": row[7],
            "last_modified": row[8].isoformat() if row[8] else None,
            "last_commit_days": row[9],
            "reference_count": row[10],
            "stale_status": row[11],
        }
        if not include_files and not item["is_directory"]:
            continue
        results.append(item)

    # Apply sorting
    reverse = direction == "desc"
    sort_keys = {
        "name": lambda x: x["name"].lower(),
        "loc": lambda x: x["lines_of_code"] or x.get("total_loc") or 0,
        "size": lambda x: x["size_bytes"] or 0,
        "files": lambda x: x["file_count"] or 0,
    }

    if sort in sort_keys:
        if folders_first:
            # Sort directories first, then files
            dirs = sorted([r for r in results if r["is_directory"]], key=sort_keys[sort], reverse=reverse)
            files = sorted([r for r in results if not r["is_directory"]], key=sort_keys[sort], reverse=reverse)
            results = dirs + files
        else:
            results = sorted(results, key=sort_keys[sort], reverse=reverse)

    return results


def list_files(
    project_id: str,
    path: str | None = None,
    extension: str | None = None,
    bloat: str | None = None,
    stale: str | None = None,
    is_directory: bool | None = None,
    sort: str = "path",
    direction: str = "asc",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """List files with filtering, sorting, and pagination."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Build WHERE clause
            conditions = ["project_id = %s"]
            params: list[Any] = [project_id]

            if path:
                conditions.append("path LIKE %s")
                params.append(f"{path}%")
            if extension:
                conditions.append("extension = %s")
                params.append(extension)
            if bloat:
                conditions.append("bloat_level = %s")
                params.append(bloat)
            if stale:
                conditions.append("stale_status = %s")
                params.append(stale)
            if is_directory is not None:
                conditions.append("is_directory = %s")
                params.append(is_directory)

            where_clause = " AND ".join(conditions)

            # Count total
            cur.execute(f"SELECT COUNT(*) FROM file_audit WHERE {where_clause}", params)
            total = cur.fetchone()[0]

            # Get results
            sort_col = {
                "path": "path",
                "lines_of_code": "lines_of_code",
                "size_bytes": "size_bytes",
                "last_commit_days": "last_commit_days",
                "reference_count": "reference_count",
            }.get(sort, "path")

            order = "DESC" if direction == "desc" else "ASC"

            cur.execute(
                f"""
                SELECT
                    path, is_directory, extension, size_bytes, lines_of_code,
                    file_count, total_loc, bloat_level, last_modified,
                    last_commit_days, reference_count, stale_status
                FROM file_audit
                WHERE {where_clause}
                ORDER BY {sort_col} {order}
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cur.fetchall()

    items = []
    for row in rows:
        items.append({
            "path": row[0],
            "name": Path(row[0]).name,
            "is_directory": row[1],
            "extension": row[2],
            "size_bytes": row[3],
            "lines_of_code": row[4],
            "file_count": row[5],
            "total_loc": row[6],
            "bloat_level": row[7],
            "last_modified": row[8].isoformat() if row[8] else None,
            "last_commit_days": row[9],
            "reference_count": row[10],
            "stale_status": row[11],
        })

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
