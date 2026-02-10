"""Test discovery - Find existing test files and match them to capabilities.

Locates test files in the codebase and extracts what they might be testing.
"""

from __future__ import annotations

from typing import TypedDict

from ...storage import explorer as explorer_storage


class TestFile(TypedDict):
    """A discovered test file with its tested subject."""

    path: str
    name: str
    tested_subject: str
    entry_id: str | None


def find_existing_tests(project_id: str) -> list[TestFile]:
    """Find test files and extract their tested subjects.

    Args:
        project_id: Project ID for scoping

    Returns:
        List of test files with suggested capability matches
    """
    all_files = explorer_storage.get_entries(project_id, {"type": "file", "limit": 10000})

    test_files: list[TestFile] = []
    test_patterns = ["test_", "_test.", ".test.", ".spec."]

    for file_entry in all_files:
        path = file_entry.get("path", "")
        name = file_entry.get("name", "")

        if not _is_test_file(path, name, test_patterns):
            continue

        test_files.append({
            "path": path,
            "name": name,
            "tested_subject": extract_test_subject(path, name),
            "entry_id": file_entry.get("id"),
        })

    return test_files


def _is_test_file(path: str, name: str, patterns: list[str]) -> bool:
    """Check if a file is a test file based on naming patterns."""
    path_lower = path.lower()
    name_lower = name.lower()
    return any(p in path_lower or p in name_lower for p in patterns)


def extract_test_subject(path: str, name: str) -> str:
    """Extract what a test file is testing.

    Args:
        path: Full file path
        name: File name

    Returns:
        Cleaned subject name (e.g., "auth" from "test_auth.py")
    """
    subject = name

    # Remove test prefixes/suffixes
    for pattern in ["test_", "_test", ".test", ".spec"]:
        subject = subject.replace(pattern, "")

    # Remove file extensions
    for ext in [".py", ".ts", ".js", ".tsx", ".jsx"]:
        subject = subject.replace(ext, "")

    return subject
