"""Architecture scanner for Explorer.

Scans for code architecture violations (parallel implementations,
missing infrastructure, duplicate utilities) and creates entries
at the file/module level with violation metadata.
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

_ZERO_COUNTS: dict[str, int] = {"parallel_implementation": 0, "missing_infrastructure": 0, "duplicate_utility": 0}


def _violation_to_dict(v: CodeViolation) -> dict[str, Any]:
    return {
        "violation_type": v.violation_type.value,
        "file_path": v.file_path,
        "detail": v.detail,
        "severity": v.severity,
        "line_start": v.line_start,
        "line_end": v.line_end,
        "related_files": v.related_files,
    }


def _scan_scope(dir_path: str) -> str:
    d = dir_path.lower()
    if "backend" in d or "app" in d:
        return "backend"
    if "frontend" in d or "src" in d or "components" in d:
        return "frontend"
    return "both"


def _build_dir_metadata(dir_path: str, violations: list[CodeViolation]) -> dict[str, Any]:
    counts: dict[str, int] = dict(_ZERO_COUNTS)
    dicts: list[dict[str, Any]] = []
    for v in violations:
        vtype = v.violation_type.value
        counts[vtype] = counts.get(vtype, 0) + 1
        dicts.append(_violation_to_dict(v))
    return {
        "scan_scope": _scan_scope(dir_path),
        "violations": dicts,
        "violation_counts": counts,
        "files_analyzed": len({v.file_path for v in violations}),
    }


def _fallback_entry() -> ExplorerEntryCreate:
    return ExplorerEntryCreate(
        path="architecture/root",
        name="codebase",
        health_status="healthy",
        metadata={"scan_scope": "both", "violations": [], "violation_counts": dict(_ZERO_COUNTS), "files_analyzed": 0},
    )


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
        """Group violations by directory/module into entries."""
        by_dir: dict[str, list[CodeViolation]] = defaultdict(list)
        for v in violations:
            by_dir[self._get_module_path(v.file_path)].append(v)

        entries = [self._make_entry(p, vs) for p, vs in by_dir.items()]
        return entries if entries else [_fallback_entry()]

    def _make_entry(self, dir_path: str, dir_violations: list[CodeViolation]) -> ExplorerEntryCreate:
        metadata = _build_dir_metadata(dir_path, dir_violations)
        return ExplorerEntryCreate(
            path=f"architecture/{dir_path}",
            name=Path(dir_path).name or dir_path,
            health_status=calculate_health_for_entry(self.entry_type, metadata),
            metadata=metadata,
        )

    def _get_module_path(self, file_path: str) -> str:
        """Get module/directory path for grouping (max 3 levels deep)."""
        path = Path(file_path)
        if self.root_path:
            with contextlib.suppress(ValueError):
                path = path.relative_to(self.root_path)
        parts = path.parts[:-1]
        if len(parts) > 3:
            parts = parts[:3]
        return "/".join(parts) if parts else str(path.parent)

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Determine health status for an architecture entry."""
        return calculate_health_for_entry(self.entry_type, entry.metadata)
