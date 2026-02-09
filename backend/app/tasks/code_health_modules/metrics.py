"""Metrics collection for weekly deep scan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


def collect_ast_metrics(
    root_path: str,
    backend_dir: str = "backend",
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Collect AST-based metrics from Python files.

    Args:
        root_path: Root path of the project
        backend_dir: Backend directory name (default: "backend")

    Returns:
        Tuple of (metrics_dict, files_with_issues)
    """
    from ...services.explorer.analyzers.ast_analyzer import parse_python_file

    scan_dir = Path(root_path) / backend_dir / "app"

    if not scan_dir.exists():
        scan_dir = Path(root_path) / "app"

    metrics = {
        "total_files": 0,
        "total_functions": 0,
        "total_classes": 0,
        "long_functions": 0,
        "large_classes": 0,
        "deep_nesting": 0,
        "max_nesting_seen": 0,
    }

    files_with_issues: list[dict[str, Any]] = []

    for py_file in scan_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            result = parse_python_file(py_file)

            metrics["total_files"] += 1
            metrics["total_functions"] += len(result["functions"])
            metrics["total_classes"] += len(result["classes"])
            metrics["max_nesting_seen"] = max(
                metrics["max_nesting_seen"],
                result["max_nesting"],
            )

            file_issues = []

            # Count long functions (>50 lines)
            for func in result["functions"]:
                if func["lines"] > 50:
                    metrics["long_functions"] += 1
                    file_issues.append(f"Long function: {func['name']} ({func['lines']} lines)")

            # Count large classes (>10 methods)
            for cls in result["classes"]:
                if len(cls["methods"]) > 10:
                    metrics["large_classes"] += 1
                    file_issues.append(
                        f"Large class: {cls['name']} ({len(cls['methods'])} methods)"
                    )

            # Count deep nesting (>3 levels)
            if result["max_nesting"] > 3:
                metrics["deep_nesting"] += 1
                file_issues.append(f"Deep nesting: {result['max_nesting']} levels")

            if file_issues:
                files_with_issues.append(
                    {
                        "file": str(py_file.relative_to(root_path)),
                        "issues": file_issues,
                    }
                )

        except (SyntaxError, FileNotFoundError) as e:
            logger.debug(f"Skipping {py_file}: {e}")
        except Exception as e:
            logger.warning(f"Failed to analyze {py_file}: {e}")

    return metrics, files_with_issues
