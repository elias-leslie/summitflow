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

import fnmatch
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
# v3: Added cyclomatic_complexity_avg, cyclomatic_complexity_max, complexity_method
METADATA_SCHEMA_VERSION = 3

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

# Magic string patterns for detection - patterns that should be constants or config
MAGIC_STRING_PATTERNS: dict[str, re.Pattern[str]] = {
    # Project-specific names that should be configurable
    "project_names": re.compile(
        r"\b(summitflow|portfolio-ai|SummitFlow)\b",
        re.IGNORECASE,
    ),
    # Hardcoded paths (absolute or well-known)
    "hardcoded_paths": re.compile(
        r'["\'](?:/home/\w+|/Users/\w+|/var/|/tmp/|/opt/|C:\\|D:\\)[^"\']*["\']',
    ),
    # Hardcoded URLs that might need to be configurable
    "hardcoded_urls": re.compile(
        r'["\']https?://(?:localhost|127\.0\.0\.1|192\.168\.|10\.|172\.(?:1[6-9]|2[0-9]|3[01])\.)[^"\']*["\']',
    ),
    # Legacy/deprecated model names
    "legacy_models": re.compile(
        r"\b(claude-3-|gemini-2\.[05]|gpt-3\.5|gpt-4-(?!turbo))\w*\b",
    ),
}

# Globs to exclude from magic string detection
MAGIC_STRING_EXCLUDE_PATTERNS: dict[str, list[str]] = {
    # Don't flag project names in documentation/tests
    "project_names": ["*.md", "*test*", "*spec*", "CLAUDE.md", "README*"],
    # Don't flag hardcoded paths in config files
    "hardcoded_paths": ["*.json", "*.yaml", "*.yml", "*.toml", "*.md"],
    # Don't flag local URLs in test files
    "hardcoded_urls": ["*test*", "*spec*", "*.md"],
    # Flag legacy models everywhere
    "legacy_models": [],
}

# Compatibility cruft patterns - indicators of technical debt
COMPAT_CRUFT_PATTERNS: dict[str, re.Pattern[str]] = {
    # Backwards compatibility comments/annotations
    "compat_comments": re.compile(
        r"#\s*(backward|backwards|compat|for\s+compat|legacy|alias|re-export)",
        re.IGNORECASE,
    ),
    # Deprecated markers
    "deprecated_markers": re.compile(
        r"#\s*(DEPRECATED|@deprecated|deprecated:)",
        re.IGNORECASE,
    ),
    # Legacy/old variable naming patterns
    "legacy_vars": re.compile(
        r"\b(\w+_old|\w+_legacy|\w+_deprecated|old_\w+|legacy_\w+|deprecated_\w+)\b",
    ),
    # Stale TODO/FIXME comments (potential technical debt)
    "stale_todos": re.compile(
        r"#\s*(TODO|FIXME|XXX|HACK)\b",
    ),
    # Alias exports/re-exports for compatibility
    "alias_exports": re.compile(
        r"^\s*\w+\s*=\s*\w+\s*#.*(?:alias|compat|legacy)",
        re.IGNORECASE | re.MULTILINE,
    ),
}

# Globs to exclude from compat cruft detection
COMPAT_CRUFT_EXCLUDE_PATTERNS: dict[str, list[str]] = {
    # Don't flag compat comments in tests (often intentional)
    "compat_comments": ["*test*", "*spec*"],
    # Deprecated markers should be flagged everywhere
    "deprecated_markers": [],
    # Don't flag legacy vars in migrations or tests
    "legacy_vars": ["*migration*", "*test*", "*spec*"],
    # Don't flag TODOs in tests (often intentional placeholders)
    "stale_todos": [],
    # Don't flag alias exports in __init__.py (often intentional)
    "alias_exports": ["__init__.py"],
}

# Code health thresholds for flag computation
CODE_HEALTH_THRESHOLDS = {
    "max_function_lines": 50,  # Functions longer than this get flagged
    "max_class_methods": 10,  # Classes with more methods get flagged
    "max_nesting_depth": 3,  # Nesting deeper than this gets flagged
    "max_functions_per_file": 20,  # Files with more functions get flagged
    "max_classes_per_file": 5,  # Files with more classes get flagged
    "max_imports": 30,  # Files with more imports get flagged
}


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

            # Use Radon CC for Python files, heuristic for others
            cc_avg: float | None = None
            cc_max: float | None = None
            complexity_method = "heuristic"

            if ext == ".py" and content:
                radon_result = self._calculate_radon_cc(content)
                if radon_result is not None:
                    cc_avg, cc_max = radon_result
                    complexity_score = cc_avg
                    complexity_method = "radon"
                else:
                    complexity_score = self._calculate_complexity_score(
                        lines, function_count, class_count
                    )
            else:
                complexity_score = self._calculate_complexity_score(
                    lines, function_count, class_count
                )

            refactor_priority = self._calculate_refactor_priority(complexity_score, lines)

            # Detect magic strings
            magic_strings = self._detect_magic_strings(rel_path, content)

            # Detect compat cruft
            compat_cruft = self._detect_compat_cruft(rel_path, content)

            # Compute health flags from thresholds
            health_flags = self._compute_health_flags(
                file_path, ext, function_count, class_count, import_count
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
                    "refactor_priority": refactor_priority,
                    "magic_strings": magic_strings if magic_strings else None,
                    "compat_cruft": compat_cruft if compat_cruft else None,
                    "health_flags": health_flags if health_flags else None,
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
        """Calculate heuristic complexity score: lines/100 + funcs/10 + classes/5.

        This is a fallback for non-Python files or when Radon fails.
        """
        return round(lines / 100 + function_count / 10 + class_count / 5, 2)

    def _calculate_radon_cc(self, content: str) -> tuple[float, float] | None:
        """Calculate cyclomatic complexity using Radon.

        Args:
            content: Python source code

        Returns:
            Tuple of (avg_cc, max_cc) or None if analysis fails
        """
        try:
            from radon.complexity import cc_visit

            results = cc_visit(content)
            if not results:
                return (0.0, 0.0)

            complexities = [r.complexity for r in results]
            avg_cc = round(sum(complexities) / len(complexities), 2)
            max_cc = float(max(complexities))
            return (avg_cc, max_cc)
        except Exception:
            # Radon can fail on syntax errors, encoding issues, etc.
            return None

    def _calculate_refactor_priority(self, complexity_score: float, lines: int) -> str:
        """Determine refactor priority based on complexity and lines."""
        if complexity_score > REFACTOR_HIGH_COMPLEXITY or lines > REFACTOR_HIGH_LINES:
            return "high"
        if complexity_score > REFACTOR_MEDIUM_COMPLEXITY or lines > REFACTOR_MEDIUM_LINES:
            return "medium"
        return "none"

    def _detect_magic_strings(self, rel_path: str, content: str) -> dict[str, int]:
        """Detect magic strings in file content.

        Returns dict mapping category -> count of matches.
        Respects exclude patterns defined in MAGIC_STRING_EXCLUDE_PATTERNS.
        """
        results: dict[str, int] = {}
        file_name = Path(rel_path).name

        for category, pattern in MAGIC_STRING_PATTERNS.items():
            # Check if file should be excluded for this category
            exclude_globs = MAGIC_STRING_EXCLUDE_PATTERNS.get(category, [])
            should_exclude = any(
                fnmatch.fnmatch(rel_path, glob) or fnmatch.fnmatch(file_name, glob)
                for glob in exclude_globs
            )
            if should_exclude:
                continue

            # Count matches
            matches = pattern.findall(content)
            if matches:
                results[category] = len(matches)

        return results

    def _detect_compat_cruft(self, rel_path: str, content: str) -> dict[str, int]:
        """Detect compatibility cruft patterns in file content.

        Returns dict mapping category -> count of matches.
        Respects exclude patterns defined in COMPAT_CRUFT_EXCLUDE_PATTERNS.
        """
        results: dict[str, int] = {}
        file_name = Path(rel_path).name

        for category, pattern in COMPAT_CRUFT_PATTERNS.items():
            # Check if file should be excluded for this category
            exclude_globs = COMPAT_CRUFT_EXCLUDE_PATTERNS.get(category, [])
            should_exclude = any(
                fnmatch.fnmatch(rel_path, glob) or fnmatch.fnmatch(file_name, glob)
                for glob in exclude_globs
            )
            if should_exclude:
                continue

            # Count matches
            matches = pattern.findall(content)
            if matches:
                results[category] = len(matches)

        return results

    def _compute_health_flags(
        self,
        file_path: Path,
        ext: str,
        function_count: int,
        class_count: int,
        import_count: int,
    ) -> dict[str, bool]:
        """Compute health flags based on thresholds and AST analysis.

        For Python files, uses AST analysis for detailed metrics.
        Returns dict of flag_name -> True if threshold exceeded.
        """
        flags: dict[str, bool] = {}

        # Basic file-level flags from already-computed counts
        if function_count > CODE_HEALTH_THRESHOLDS["max_functions_per_file"]:
            flags["too_many_functions"] = True
        if class_count > CODE_HEALTH_THRESHOLDS["max_classes_per_file"]:
            flags["too_many_classes"] = True
        if import_count > CODE_HEALTH_THRESHOLDS["max_imports"]:
            flags["too_many_imports"] = True

        # Python-specific AST analysis for detailed metrics
        if ext == ".py" and file_path.exists():
            try:
                from ..analyzers.ast_analyzer import parse_python_file

                result = parse_python_file(file_path)

                # Check for long functions
                for func in result["functions"]:
                    if func["lines"] > CODE_HEALTH_THRESHOLDS["max_function_lines"]:
                        flags["has_long_functions"] = True
                        break

                # Check for large classes (many methods)
                for cls in result["classes"]:
                    if len(cls["methods"]) > CODE_HEALTH_THRESHOLDS["max_class_methods"]:
                        flags["has_large_classes"] = True
                        break

                # Check for deep nesting
                if result["max_nesting"] > CODE_HEALTH_THRESHOLDS["max_nesting_depth"]:
                    flags["deep_nesting"] = True

            except (SyntaxError, FileNotFoundError, Exception):
                # Skip AST analysis for unparseable files
                pass

        return flags

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
        # Maps: path -> (timestamp, hash, message)
        last_commit_map = self._get_all_last_commits()

        # Batch 2: Get 90-day commit counts for ALL files (single git call)
        # Maps: path -> count
        commit_count_map = self._get_all_commit_counts_90d()

        # Apply git info to entries
        for entry in entries:
            if entry.metadata.get("is_directory"):
                continue

            path = entry.path

            # Apply last commit info
            if path in last_commit_map:
                timestamp, commit_hash, message = last_commit_map[path]
                commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
                days = (now - commit_time).days
                entry.metadata["last_commit_days"] = days
                entry.metadata["last_commit_hash"] = commit_hash
                entry.metadata["last_commit_message"] = message[:100] if message else ""
                entry.metadata["stale_status"] = (
                    "stale" if days >= STALE_THRESHOLD_DAYS else "fresh"
                )
            else:
                entry.metadata["stale_status"] = "unknown"

            # Apply commit count
            entry.metadata["commit_count_90d"] = commit_count_map.get(path, 0)

            # Check if test file exists (filesystem check - fast)
            entry.metadata["test_file_exists"] = self._has_test_file(path, entry.name)

    def _get_all_last_commits(self) -> dict[str, tuple[int, str, str]]:
        """Get last commit info for ALL files in one git call.

        Uses git log with --name-only to get commit info with filenames.
        Returns dict mapping path -> (timestamp, hash, message).
        """
        if not self.root_path:
            return {}

        try:
            # Use null separators for reliable parsing
            # Format: timestamp|hash|subject, then files on separate lines
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--all",
                    "--name-only",
                    "--format=%x00%at|%h|%s",  # null byte before each commit
                    "--diff-filter=ACMRT",  # Added, Copied, Modified, Renamed, Type-changed
                ],
                cwd=str(self.root_path),
                capture_output=True,
                text=True,
                timeout=60,  # Allow more time for full history
                check=False,
            )

            if result.returncode != 0:
                logger.warning(f"git log for last commits failed: {result.stderr}")
                return {}

            # Parse output to build file -> latest commit map
            # We only keep the FIRST (most recent) commit for each file
            file_commits: dict[str, tuple[int, str, str]] = {}
            current_commit: tuple[int, str, str] | None = None

            for line in result.stdout.split("\n"):
                if line.startswith("\x00"):
                    # New commit header
                    parts = line[1:].split("|", 2)
                    if len(parts) >= 3 and parts[0]:
                        try:
                            current_commit = (int(parts[0]), parts[1], parts[2])
                        except ValueError:
                            current_commit = None
                elif line.strip() and current_commit:
                    # File name - only record if we haven't seen this file yet
                    file_path = line.strip()
                    if file_path not in file_commits:
                        file_commits[file_path] = current_commit

            logger.info(f"Batch git: got last commit info for {len(file_commits)} files")
            return file_commits

        except subprocess.TimeoutExpired:
            logger.warning("git log for last commits timed out")
            return {}
        except OSError as e:
            logger.warning(f"git log for last commits failed: {e}")
            return {}

    def _get_all_commit_counts_90d(self) -> dict[str, int]:
        """Get 90-day commit counts for ALL files in one git call.

        Returns dict mapping path -> commit_count.
        """
        if not self.root_path:
            return {}

        try:
            # Get all files changed in commits from last 90 days
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--since=90 days ago",
                    "--name-only",
                    "--format=",  # No commit info, just filenames
                    "--diff-filter=ACMRT",
                ],
                cwd=str(self.root_path),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            if result.returncode != 0:
                logger.warning(f"git log for commit counts failed: {result.stderr}")
                return {}

            # Count occurrences of each file
            from collections import Counter

            file_counts: Counter[str] = Counter()
            for line in result.stdout.split("\n"):
                path = line.strip()
                if path:
                    file_counts[path] += 1

            logger.info(f"Batch git: got 90-day commit counts for {len(file_counts)} files")
            return dict(file_counts)

        except subprocess.TimeoutExpired:
            logger.warning("git log for commit counts timed out")
            return {}
        except OSError as e:
            logger.warning(f"git log for commit counts failed: {e}")
            return {}

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
