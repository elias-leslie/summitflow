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


def detect_magic_strings(rel_path: str, content: str) -> dict[str, int]:
    """Detect magic strings in file content.

    Args:
        rel_path: Relative path to file
        content: File content to scan

    Returns:
        Dict mapping category -> count of matches.
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


def detect_compat_cruft(rel_path: str, content: str) -> dict[str, int]:
    """Detect compatibility cruft patterns in file content.

    Args:
        rel_path: Relative path to file
        content: File content to scan

    Returns:
        Dict mapping category -> count of matches.
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
