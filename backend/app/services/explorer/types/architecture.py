"""Architecture scanner for Explorer.

Scans for code architecture violations across the codebase:
- Parallel implementations (multiple implementations of same functionality)
- Missing infrastructure (caching, error handling, observability)
- Duplicate utilities (literal code duplication)

Creates entries at the file/module level with violation metadata.

Metadata schema:
{
    "scan_scope": "backend" | "frontend" | "both",
    "violations": [
        {
            "violation_type": "parallel_implementation" | "missing_infrastructure" | "duplicate_utility",
            "detail": "Description of the violation",
            "severity": "error" | "warning",
            "line_start": 123,
            "line_end": 456,
            "related_files": ["path/to/related.py"]
        }
    ],
    "violation_counts": {
        "parallel_implementation": 0,
        "missing_infrastructure": 1,
        "duplicate_utility": 2
    },
    "files_analyzed": 42,
    "last_scan_duration_ms": 1234
}
"""

from __future__ import annotations

import contextlib
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate
from .code_violations import CodeViolation, CodeViolationDetector

logger = get_logger(__name__)


class CodeArchitectureScanner(BaseScanner):
    """Scans codebase for architecture violations."""

    entry_type = "architecture"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self._detector: CodeViolationDetector | None = None

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan for architecture violations and return entries."""
        root = get_project_root(self.project_id)
        if not root:
            logger.error(f"No root_path configured for project {self.project_id}")
            return []

        self.root_path = Path(root)
        if not self.root_path.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return []

        logger.info(f"Architecture scan started for {self.project_id}: {self.root_path}")
        start_time = time.time()

        backend_dir = self.config.get("backend_dir", "backend")
        self._detector = CodeViolationDetector(self.root_path, backend_dir)

        violations = self._detector.detect_violations()

        entries = self._group_violations_to_entries(violations)

        duration_ms = int((time.time() - start_time) * 1000)

        for entry in entries:
            entry.metadata["last_scan_duration_ms"] = duration_ms

        logger.info(
            f"Architecture scan found {len(violations)} violations "
            f"across {len(entries)} entries in {duration_ms}ms"
        )

        return entries

    def _group_violations_to_entries(
        self, violations: list[CodeViolation]
    ) -> list[ExplorerEntryCreate]:
        """Group violations by directory/module into entries.

        Creates one entry per affected directory with all its violations.
        """
        entries: list[ExplorerEntryCreate] = []

        violations_by_dir: dict[str, list[CodeViolation]] = defaultdict(list)
        for v in violations:
            dir_path = self._get_module_path(v.file_path)
            violations_by_dir[dir_path].append(v)

        for dir_path, dir_violations in violations_by_dir.items():
            violation_counts: dict[str, int] = {
                "parallel_implementation": 0,
                "missing_infrastructure": 0,
                "duplicate_utility": 0,
            }

            violation_dicts: list[dict[str, Any]] = []

            for v in dir_violations:
                vtype = v.violation_type.value
                violation_counts[vtype] = violation_counts.get(vtype, 0) + 1

                violation_dicts.append(
                    {
                        "violation_type": vtype,
                        "file_path": v.file_path,
                        "detail": v.detail,
                        "severity": v.severity,
                        "line_start": v.line_start,
                        "line_end": v.line_end,
                        "related_files": v.related_files,
                    }
                )

            scan_scope = self._determine_scan_scope(dir_path)
            files_analyzed = len({v.file_path for v in dir_violations})

            metadata = {
                "scan_scope": scan_scope,
                "violations": violation_dicts,
                "violation_counts": violation_counts,
                "files_analyzed": files_analyzed,
            }

            name = Path(dir_path).name or dir_path
            health = calculate_health_for_entry(self.entry_type, metadata)

            entries.append(
                ExplorerEntryCreate(
                    path=f"architecture/{dir_path}",
                    name=name,
                    health_status=health,
                    metadata=metadata,
                )
            )

        if not entries and self.root_path:
            entries.append(
                ExplorerEntryCreate(
                    path="architecture/root",
                    name="codebase",
                    health_status="healthy",
                    metadata={
                        "scan_scope": "both",
                        "violations": [],
                        "violation_counts": {
                            "parallel_implementation": 0,
                            "missing_infrastructure": 0,
                            "duplicate_utility": 0,
                        },
                        "files_analyzed": 0,
                    },
                )
            )

        return entries

    def _get_module_path(self, file_path: str) -> str:
        """Get the module/directory path for grouping.

        Groups violations at the package level (e.g., backend/app/services).
        """
        path = Path(file_path)

        if self.root_path:
            with contextlib.suppress(ValueError):
                path = path.relative_to(self.root_path)

        parts = path.parts[:-1]

        if len(parts) > 3:
            parts = parts[:3]

        return "/".join(parts) if parts else str(path.parent)

    def _determine_scan_scope(self, dir_path: str) -> str:
        """Determine if a path is backend, frontend, or both."""
        dir_lower = dir_path.lower()
        if "backend" in dir_lower or "app" in dir_lower:
            return "backend"
        if "frontend" in dir_lower or "src" in dir_lower or "components" in dir_lower:
            return "frontend"
        return "both"

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for an architecture entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
