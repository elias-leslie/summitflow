"""Utility functions for file scanning.

Includes directory aggregation, test file detection, and helper functions.
Extracted from files.py for focused responsibility.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import ExplorerEntryCreate


def aggregate_to_parents(
    rel_path: str, entry: ExplorerEntryCreate, dir_stats: dict[str, dict[str, Any]]
) -> None:
    """Aggregate file stats to parent directories.

    Modifies dir_stats dict in place.

    Args:
        rel_path: Relative path to file
        entry: Explorer entry for the file
        dir_stats: Dict to accumulate directory statistics
    """
    path_parts = Path(rel_path).parts[:-1]
    lines = entry.metadata.get("lines_of_code", 0)

    for i in range(len(path_parts)):
        dir_path = str(Path(*path_parts[: i + 1]))
        if dir_path not in dir_stats:
            dir_stats[dir_path] = {"file_count": 0, "total_loc": 0}
        dir_stats[dir_path]["file_count"] += 1
        dir_stats[dir_path]["total_loc"] += lines


def create_directory_entries(dir_stats: dict[str, dict[str, Any]]) -> list[ExplorerEntryCreate]:
    """Create entries for directories from aggregated stats.

    Args:
        dir_stats: Dict of directory path -> stats

    Returns:
        List of explorer entries for directories
    """
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


def has_test_file(root_path: Path, file_path: str, file_name: str) -> bool:
    """Check if a test file exists for this source file.

    Args:
        root_path: Root directory of project
        file_path: Relative path to source file
        file_name: Name of source file

    Returns:
        True if test file exists, False otherwise
    """
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
            test_path = root_path / test_dir / pattern
            if test_path.exists():
                return True

    return False
