"""Test importer service - Import existing tests from projects into registry.

This module provides test discovery and import for various test frameworks:
- pytest: Python unit/integration tests
- vitest: JavaScript/TypeScript unit tests

Tests are discovered via framework-specific methods and registered in the
centralized test registry for tracking and execution.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from glob import glob
from typing import Any

from ..storage import tests as tests_storage
from ..storage.connection import get_connection

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredTest:
    """A test discovered from the project."""

    test_id: str
    name: str
    test_type: str
    command: str
    working_dir: str | None = None
    config: dict[str, Any] | None = None


@dataclass
class ImportResult:
    """Result of a test import operation."""

    imported_count: int
    skipped_count: int
    tests: list[dict[str, Any]]
    errors: list[str]


def get_project_paths(project_id: str) -> tuple[str, str, str] | None:
    """Get project paths from database.

    Returns:
        Tuple of (root_path, backend_root, frontend_root) or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT root_path, test_config
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    root_path = row[0] or "."
    test_config = row[1] or {}

    # Handle JSON string if needed
    import json

    if isinstance(test_config, str):
        test_config = json.loads(test_config)

    backend_root = test_config.get("backend_root", "backend")
    frontend_root = test_config.get("frontend_root", "frontend")

    return (root_path, backend_root, frontend_root)


async def import_tests(
    project_id: str,
    source_type: str,
    discover: bool = True,
) -> ImportResult:
    """Import tests from a project.

    Args:
        project_id: Project ID
        source_type: Type of tests to import ('pytest', 'vitest', 'all')
        discover: Whether to run discovery (True) or just check existing

    Returns:
        ImportResult with counts and imported tests.

    Raises:
        ValueError: If project not found.
    """
    paths = get_project_paths(project_id)
    if not paths:
        raise ValueError(f"Project not found: {project_id}")

    root_path, backend_root, frontend_root = paths

    from collections.abc import Callable

    importers: dict[str, Callable[[], Any]] = {
        "pytest": lambda: discover_pytest_tests(project_id, root_path, backend_root),
        "vitest": lambda: discover_vitest_tests(project_id, root_path, frontend_root),
    }

    all_discovered: list[DiscoveredTest] = []
    errors: list[str] = []

    if source_type == "all":
        for name, importer in importers.items():
            try:
                tests = await importer()
                all_discovered.extend(tests)
            except Exception as e:
                errors.append(f"{name}: {e}")
    elif source_type in importers:
        try:
            all_discovered = await importers[source_type]()
        except Exception as e:
            errors.append(f"{source_type}: {e}")
    else:
        raise ValueError(f"Unknown source type: {source_type}")

    # Import discovered tests into registry
    imported = []
    skipped = 0

    for test in all_discovered:
        # Check if test already exists
        existing = tests_storage.get_test(project_id, test.test_id)
        if existing:
            skipped += 1
            continue

        # Create test entry
        try:
            created = tests_storage.create_test(
                project_id=project_id,
                test_id=test.test_id,
                name=test.name,
                test_type=test.test_type,
                command=test.command,
                working_dir=test.working_dir,
                config=test.config,
            )
            imported.append(created)
        except Exception as e:
            errors.append(f"Failed to create {test.test_id}: {e}")

    return ImportResult(
        imported_count=len(imported),
        skipped_count=skipped,
        tests=imported,
        errors=errors,
    )


# ============================================================
# Pytest Discovery
# ============================================================


async def discover_pytest_tests(
    project_id: str,
    root_path: str,
    backend_root: str,
) -> list[DiscoveredTest]:
    """Discover pytest tests via pytest --collect-only.

    Args:
        project_id: Project ID
        root_path: Project root path
        backend_root: Backend directory relative to root

    Returns:
        List of discovered tests.
    """
    working_dir = os.path.join(root_path, backend_root)

    if not os.path.exists(working_dir):
        return []

    # Run pytest --collect-only to discover tests
    # Use --quiet --quiet (-qq) to get parseable "file::test" format
    proc = await asyncio.create_subprocess_shell(
        ".venv/bin/pytest --collect-only --quiet --quiet 2>/dev/null || pytest --collect-only --quiet --quiet 2>/dev/null",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=working_dir,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")

    discovered = []

    # Parse output - each line is like: tests/test_file.py::test_function
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("=") or line.startswith("<"):
            continue

        # Match test patterns
        match = re.match(r"^(.+\.py)::(.+)$", line)
        if match:
            file_path = match.group(1)
            test_name = match.group(2)

            # Generate test_id from path (truncate to 100 chars for DB constraint)
            test_id = f"pytest-{file_path.replace('/', '-').replace('.py', '')}-{test_name}".lower()
            test_id = re.sub(r"[^a-z0-9-]", "-", test_id)
            test_id = test_id[:100]  # DB constraint

            discovered.append(
                DiscoveredTest(
                    test_id=test_id,
                    name=f"{file_path}::{test_name}",
                    test_type="pytest",
                    command=f"{file_path}::{test_name}",
                    working_dir=working_dir,
                )
            )

    return discovered


# ============================================================
# Vitest Discovery
# ============================================================


async def discover_vitest_tests(
    project_id: str,
    root_path: str,
    frontend_root: str,
) -> list[DiscoveredTest]:
    """Discover vitest tests via glob patterns.

    Args:
        project_id: Project ID
        root_path: Project root path
        frontend_root: Frontend directory relative to root

    Returns:
        List of discovered tests.
    """
    working_dir = os.path.join(root_path, frontend_root)

    if not os.path.exists(working_dir):
        return []

    discovered = []

    # Glob for test files
    patterns = [
        "**/*.test.ts",
        "**/*.test.tsx",
        "**/*.spec.ts",
        "**/*.spec.tsx",
    ]

    for pattern in patterns:
        for file_path in glob(os.path.join(working_dir, pattern), recursive=True):
            # Get relative path
            rel_path = os.path.relpath(file_path, working_dir)

            # Skip node_modules
            if "node_modules" in rel_path:
                continue

            # Generate test_id from path (truncate to 100 chars for DB constraint)
            test_id = f"vitest-{rel_path.replace('/', '-').replace('.test', '').replace('.spec', '').replace('.ts', '').replace('.tsx', '')}".lower()
            test_id = re.sub(r"[^a-z0-9-]", "-", test_id)
            test_id = test_id[:100]  # DB constraint

            discovered.append(
                DiscoveredTest(
                    test_id=test_id,
                    name=rel_path,
                    test_type="vitest",
                    command=rel_path,
                    working_dir=working_dir,
                )
            )

    return discovered


# ============================================================
# Manual Test Creation
# ============================================================


def create_manual_test(
    project_id: str,
    test_id: str,
    name: str,
    test_type: str,
    command: str | None = None,
    script: str | None = None,
    config: dict[str, Any] | None = None,
    working_dir: str | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Manually create a test entry.

    Use this for API tests, UI tests, or custom tests that can't be auto-discovered.

    Args:
        project_id: Project ID
        test_id: Unique test identifier
        name: Human-readable test name
        test_type: Type of test (pytest, mypy, ruff, vitest, api, ui)
        command: Command to run the test
        script: Script content for UI tests
        config: Additional configuration as JSON
        working_dir: Working directory for test execution
        timeout_seconds: Timeout in seconds

    Returns:
        The created test dict.
    """
    return tests_storage.create_test(
        project_id=project_id,
        test_id=test_id,
        name=name,
        test_type=test_type,
        command=command,
        script=script,
        config=config,
        working_dir=working_dir,
        timeout_seconds=timeout_seconds,
    )
