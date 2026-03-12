"""Pattern detection for files: magic strings, compat cruft, health flags.

Extracted from files.py for focused responsibility.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

from .file_constants import (
    CODE_HEALTH_THRESHOLDS,
    COMPAT_CRUFT_EXCLUDE_PATTERNS,
    COMPAT_CRUFT_PATTERNS,
    MAGIC_STRING_EXCLUDE_PATTERNS,
    MAGIC_STRING_PATTERNS,
)


def _is_excluded(rel_path: str, file_name: str, exclude_globs: list[str]) -> bool:
    """Return True if the file matches any exclude glob."""
    return any(
        fnmatch.fnmatch(rel_path, glob) or fnmatch.fnmatch(file_name, glob)
        for glob in exclude_globs
    )


def _count_pattern_matches(
    rel_path: str,
    file_name: str,
    content: str,
    patterns: dict,
    exclude_patterns: dict,
) -> dict[str, int]:
    """Count regex pattern matches per category, respecting exclude globs."""
    results: dict[str, int] = {}
    for category, pattern in patterns.items():
        exclude_globs = exclude_patterns.get(category, [])
        if _is_excluded(rel_path, file_name, exclude_globs):
            continue
        matches = pattern.findall(content)
        if matches:
            results[category] = len(matches)
    return results


def detect_magic_strings(rel_path: str, content: str) -> dict[str, int]:
    """Detect magic strings in file content.

    Args:
        rel_path: Relative path to file
        content: File content to scan

    Returns:
        Dict mapping category -> count of matches.
        Respects exclude patterns defined in MAGIC_STRING_EXCLUDE_PATTERNS.
    """
    return _count_pattern_matches(
        rel_path,
        Path(rel_path).name,
        content,
        MAGIC_STRING_PATTERNS,
        MAGIC_STRING_EXCLUDE_PATTERNS,
    )


def detect_compat_cruft(rel_path: str, content: str) -> dict[str, int]:
    """Detect compatibility cruft patterns in file content.

    Args:
        rel_path: Relative path to file
        content: File content to scan

    Returns:
        Dict mapping category -> count of matches.
        Respects exclude patterns defined in COMPAT_CRUFT_EXCLUDE_PATTERNS.
    """
    return _count_pattern_matches(
        rel_path,
        Path(rel_path).name,
        content,
        COMPAT_CRUFT_PATTERNS,
        COMPAT_CRUFT_EXCLUDE_PATTERNS,
    )


def _has_long_functions(functions: list[dict]) -> bool:
    """Return True if any function exceeds the max line threshold."""
    return any(
        f["lines"] > CODE_HEALTH_THRESHOLDS["max_function_lines"]
        for f in functions
    )


def _has_large_classes(classes: list[dict]) -> bool:
    """Return True if any class has too many methods."""
    return any(
        len(cls["methods"]) > CODE_HEALTH_THRESHOLDS["max_class_methods"]
        for cls in classes
    )


def _compute_python_ast_flags(file_path: Path) -> dict[str, bool]:
    """Run AST analysis on a Python file and return health flags."""
    flags: dict[str, bool] = {}
    try:
        from ..analyzers.ast_analyzer import parse_python_file

        result = parse_python_file(file_path)
        if _has_long_functions(result["functions"]):
            flags["has_long_functions"] = True
        if _has_large_classes(result["classes"]):
            flags["has_large_classes"] = True
        if result["max_nesting"] > CODE_HEALTH_THRESHOLDS["max_nesting_depth"]:
            flags["deep_nesting"] = True
    except Exception:
        pass  # Skip AST analysis for unparseable files
    return flags


def compute_health_flags(
    file_path: Path,
    ext: str,
    function_count: int,
    class_count: int,
    import_count: int,
) -> dict[str, bool]:
    """Compute health flags based on thresholds and AST analysis.

    For Python files, uses AST analysis for detailed metrics.

    Args:
        file_path: Path to file
        ext: File extension
        function_count: Number of functions
        class_count: Number of classes
        import_count: Number of imports

    Returns:
        Dict of flag_name -> True if threshold exceeded.
    """
    flags: dict[str, bool] = {}

    if function_count > CODE_HEALTH_THRESHOLDS["max_functions_per_file"]:
        flags["too_many_functions"] = True
    if class_count > CODE_HEALTH_THRESHOLDS["max_classes_per_file"]:
        flags["too_many_classes"] = True
    if import_count > CODE_HEALTH_THRESHOLDS["max_imports"]:
        flags["too_many_imports"] = True

    if ext == ".py" and file_path.exists():
        flags.update(_compute_python_ast_flags(file_path))

    return flags
