"""Code violation detector for Explorer.

Detects architecture violations across the codebase:
- PARALLEL_IMPLEMENTATION: Multiple implementations of the same functionality
- MISSING_INFRASTRUCTURE: Missing caching, error handling, observability patterns
- DUPLICATE_UTILITY: Literal code duplication (copy-paste)

Uses external tools:
- jscpd: Copy-paste detection (10+ tokens, 2+ copies)
- vulture: Python dead code detection (--min-confidence 80)
- semgrep: Pattern-based detection for missing infrastructure
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ViolationType(Enum):
    PARALLEL_IMPLEMENTATION = "parallel_implementation"
    MISSING_INFRASTRUCTURE = "missing_infrastructure"
    DUPLICATE_UTILITY = "duplicate_utility"


@dataclass
class CodeViolation:
    violation_type: ViolationType
    file_path: str
    detail: str
    severity: str = "warning"
    line_start: int | None = None
    line_end: int | None = None
    related_files: list[str] = field(default_factory=list)


# NOTE: violation_detectors and violation_parsers import CodeViolation and
# ViolationType from this module.  The definitions above MUST stay above this
# import so that names are already bound when the circular import resolves.
from .violation_detectors import (  # noqa: E402
    detect_dead_code,
    detect_duplicates,
    detect_missing_infrastructure,
    find_pattern_implementations,
)

__all__ = ["CodeViolation", "CodeViolationDetector", "ViolationType"]


class CodeViolationDetector:
    """Detects code architecture violations using external tools.

    Detection logic lives in ``violation_detectors``; this class owns
    configuration and the public API only.
    """

    def __init__(self, project_root: Path, backend_dir: str = "backend") -> None:
        self.project_root = project_root
        self.backend_dir = backend_dir
        self._semgrep_rules_dir = project_root / ".semgrep"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_violations(self) -> list[CodeViolation]:
        """Detect all code violations in the project."""
        violations: list[CodeViolation] = []
        violations.extend(detect_duplicates(self.project_root, self.backend_dir))
        violations.extend(detect_dead_code(self.project_root, self.backend_dir))
        violations.extend(
            detect_missing_infrastructure(
                self.project_root, self.backend_dir, self._semgrep_rules_dir
            )
        )
        return violations

    def detect_parallel_implementations(
        self,
        pattern_name: str,
        search_paths: list[Path],
    ) -> list[CodeViolation]:
        """Detect parallel implementations of a named pattern.

        Args:
            pattern_name: Human-readable name of the pattern
            search_paths: Paths to search for implementations

        Returns:
            Violations if multiple implementations found
        """
        implementations = find_pattern_implementations(pattern_name, search_paths)
        if len(implementations) <= 1:
            return []

        files = [str(p) for p, _ in implementations]
        return [
            CodeViolation(
                violation_type=ViolationType.PARALLEL_IMPLEMENTATION,
                file_path=str(implementations[0][0]),
                detail=(
                    f"Multiple implementations of '{pattern_name}' found "
                    f"in {len(implementations)} files"
                ),
                severity="error",
                line_start=implementations[0][1],
                related_files=files[1:],
            )
        ]

    def get_violation_summary(self, violations: list[CodeViolation]) -> dict[str, Any]:
        """Get a summary of violations by type and severity."""
        summary: dict[str, Any] = {
            "total": len(violations),
            "by_type": {},
            "by_severity": {"error": 0, "warning": 0},
            "files_affected": set(),
        }

        for v in violations:
            type_name = v.violation_type.value
            summary["by_type"][type_name] = summary["by_type"].get(type_name, 0) + 1
            summary["by_severity"][v.severity] = summary["by_severity"].get(v.severity, 0) + 1
            summary["files_affected"].add(v.file_path)

        summary["files_affected"] = len(summary["files_affected"])
        return summary
