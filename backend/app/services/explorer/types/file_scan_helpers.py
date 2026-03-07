"""Helpers for file scanning: complexity computation and metadata building.

Extracted from files.py to keep FileScanner under the line-count limit.
"""

from __future__ import annotations

from typing import NamedTuple

from .file_complexity import (
    analyze_python_complexity,
    build_refactor_issues,
    calculate_complexity_score,
    calculate_refactor_priority,
)
from .file_constants import METADATA_SCHEMA_VERSION


class ComplexityResult(NamedTuple):
    """Holds all complexity metrics for a scanned file."""

    score: float
    method: str
    cc_avg: float | None
    cc_max: float | None
    comment_density: float | None


def compute_file_complexity(
    ext: str, content: str, lines: int, function_count: int, class_count: int
) -> ComplexityResult:
    """Compute complexity metrics; uses Radon for Python, heuristic otherwise."""
    if ext == ".py" and content:
        score, method, cc_avg, cc_max, density = analyze_python_complexity(
            content, lines, function_count, class_count
        )
        return ComplexityResult(score, method, cc_avg, cc_max, density)
    return ComplexityResult(
        calculate_complexity_score(lines, function_count, class_count),
        "heuristic",
        None,
        None,
        None,
    )


def compute_refactor_fields(
    complexity: ComplexityResult,
    lines: int,
    health_flags: list[str] | None,
    bloat_level: str | None,
    magic_strings: list[str] | None,
    compat_cruft: list[str] | None,
) -> tuple[str, list[str] | None]:
    """Return (refactor_priority, refactor_issues) for a file."""
    priority = calculate_refactor_priority(
        complexity.score, lines,
        health_flags=health_flags or None,
        bloat_level=bloat_level,
    )
    issues = build_refactor_issues(
        complexity.score, lines,
        health_flags=health_flags or None,
        bloat_level=bloat_level,
        magic_strings=magic_strings or None,
        compat_cruft=compat_cruft or None,
    )
    return priority, issues or None


def build_file_metadata(
    ext: str,
    size_bytes: int,
    lines: int,
    bloat_level: str | None,
    function_count: int,
    class_count: int,
    import_count: int,
    complexity: ComplexityResult,
    refactor_priority: str,
    refactor_issues: list[str] | None,
    magic_strings: list[str] | None,
    compat_cruft: list[str] | None,
    health_flags: list[str] | None,
    symbol_count: int = 0,
    symbol_kinds: dict[str, int] | None = None,
) -> dict[str, object]:
    """Build the metadata dict for a file entry."""
    return {
        "_schema_version": METADATA_SCHEMA_VERSION,
        "is_directory": False,
        "extension": ext or None,
        "size_bytes": size_bytes,
        "lines_of_code": lines,
        "bloat_level": bloat_level,
        "function_count": function_count,
        "class_count": class_count,
        "import_count": import_count,
        "complexity_score": complexity.score,
        "complexity_method": complexity.method,
        "cyclomatic_complexity_avg": complexity.cc_avg,
        "cyclomatic_complexity_max": complexity.cc_max,
        "comment_density": complexity.comment_density,
        "refactor_priority": refactor_priority,
        "refactor_issues": refactor_issues,
        "magic_strings": magic_strings or None,
        "compat_cruft": compat_cruft or None,
        "health_flags": health_flags or None,
        "symbol_count": symbol_count,
        "symbol_kinds": symbol_kinds or None,
    }
