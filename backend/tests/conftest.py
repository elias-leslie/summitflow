"""Test configuration and fixtures.

Provides FastAPI TestClient and database isolation.

CRITICAL: Tests NEVER touch production database. All tests run against
summitflow_test database with isolated transactions that rollback.
"""

from __future__ import annotations

# =============================================================================
# PRODUCTION DATABASE GUARD - MUST RUN BEFORE ANY APP IMPORTS
# =============================================================================
# This runs at module load time, BEFORE pytest_configure, to ensure
# DATABASE_URL is overridden before any app modules read it.
import os
import sys
from collections.abc import Callable, Generator
from pathlib import Path

from dotenv import load_dotenv

# Load env vars FIRST
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)

_db_url = os.environ.get("DATABASE_URL", "")
_test_db_url = os.environ.get("TEST_DATABASE_URL", "")

# Check if pointing at production database
_is_production = "/summitflow" in _db_url and "/summitflow_test" not in _db_url and not _test_db_url

if _is_production:
    print("\n" + "=" * 70, file=sys.stderr)
    print("FATAL: REFUSING TO RUN TESTS AGAINST PRODUCTION DATABASE", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"\nDATABASE_URL points to: {_db_url}", file=sys.stderr)
    print("\nTests require one of:", file=sys.stderr)
    print("  1. TEST_DATABASE_URL env var pointing to summitflow_test", file=sys.stderr)
    print("  2. DATABASE_URL pointing to summitflow_test (not summitflow)", file=sys.stderr)
    print("\nTo fix, add to ~/.env.local:", file=sys.stderr)
    print(
        "  TEST_DATABASE_URL=postgresql://summitflow_app:PASSWORD@localhost:5432/summitflow_test",
        file=sys.stderr,
    )
    print("\nOr create the test database:", file=sys.stderr)
    print("  sudo -u postgres createdb summitflow_test", file=sys.stderr)
    print(
        '  sudo -u postgres psql -c "GRANT ALL ON DATABASE summitflow_test TO summitflow_app;"',
        file=sys.stderr,
    )
    print("=" * 70 + "\n", file=sys.stderr)
    sys.exit(1)

# If TEST_DATABASE_URL is set, override DATABASE_URL BEFORE any app imports
if _test_db_url:
    os.environ["DATABASE_URL"] = _test_db_url
    print(
        f"\n[TEST] Using TEST_DATABASE_URL: {_test_db_url.split('@')[1] if '@' in _test_db_url else _test_db_url}"
    )

# =============================================================================
# NOW safe to import from app modules
# =============================================================================

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom pytest command-line options."""
    parser.addoption(
        "--run-live-agent-hub",
        action="store_true",
        default=False,
        help="Run live integration tests against Agent Hub (uses tokens)",
    )
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run E2E tests that hit real databases and services (DANGEROUS)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark test as E2E (requires --run-e2e)")
    config.addinivalue_line("markers", "integration: mark test as integration test")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip E2E and integration tests unless explicitly enabled."""
    from pathlib import Path

    run_e2e = config.getoption("--run-e2e")
    skip_e2e = pytest.mark.skip(
        reason="E2E tests skipped. Use --run-e2e to run (DANGEROUS: hits production DB!)"
    )

    tests_dir = Path(__file__).parent

    for item in items:
        item_path = Path(str(getattr(item, "fspath", "")))

        # Auto-mark tests in e2e/ or integration/ directories
        try:
            rel_path = item_path.relative_to(tests_dir)
            if str(rel_path).startswith("e2e/") or str(rel_path).startswith("integration/"):
                item.add_marker(pytest.mark.e2e)
        except ValueError:
            pass

        # Skip e2e tests unless --run-e2e
        if "e2e" in item.keywords and not run_e2e:
            item.add_marker(skip_e2e)


# =============================================================================
# DATABASE FIXTURES
# =============================================================================


@pytest.fixture(scope="session")
def test_db_url() -> str:
    """Get the test database URL."""
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("No database URL configured for tests")
    return url


@pytest.fixture(scope="session")
def db_schema_initialized(test_db_url: str) -> Generator[None]:
    """Initialize test database schema once per session."""
    from app.storage.connection import close_pool, init_schema

    init_schema()
    yield
    close_pool()


# =============================================================================
# CLI OUTPUT STATE FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def reset_cli_output_state() -> Generator[None]:
    """Reset CLI output module state before each test.

    The CLI output module uses global state for output formatting.
    Tests that set compact/human/progress_only modes can leak state
    to other tests if not properly reset. This fixture ensures
    clean state for every test.
    """
    from cli.output import set_compact_output, set_human_output, set_progress_only

    # Reset to defaults before test
    set_compact_output(False)
    set_human_output(False)
    set_progress_only(False)
    yield
    # Reset again after test (in case test forgot to cleanup)
    set_compact_output(False)
    set_human_output(False)
    set_progress_only(False)


# =============================================================================
# TEST CLIENT FIXTURES
# =============================================================================


@pytest.fixture
def client(db_schema_initialized: None) -> TestClient:
    """FastAPI test client with database initialized."""
    from app.main import app

    return TestClient(app)


@pytest.fixture
def test_project_id() -> str:
    """Return a test project ID."""
    return "test-project"


@pytest.fixture
def ensure_test_project(db_schema_initialized: None) -> str:
    """Ensure test project exists in database."""
    from app.storage.connection import get_connection

    project_id = "test-project"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Project", "http://localhost:3001"),
        )
        conn.commit()
    return project_id


# =============================================================================
# TASK CLEANUP FIXTURES
# =============================================================================


@pytest.fixture
def cleanup_task(db_schema_initialized: None) -> Generator[Callable[[str], None]]:
    """Fixture that returns a cleanup function for tasks."""
    from app.storage.connection import get_connection

    created_tasks = []

    def _cleanup_task(task_id: str) -> None:
        created_tasks.append(task_id)

    yield _cleanup_task

    # Cleanup after test
    if created_tasks:
        with get_connection() as conn, conn.cursor() as cur:
            for task_id in created_tasks:
                # Delete in order: steps -> subtasks -> spirit -> labels -> deps -> task
                cur.execute(
                    "DELETE FROM task_subtask_steps WHERE subtask_id IN (SELECT id FROM task_subtasks WHERE task_id = %s)",
                    (task_id,),
                )
                cur.execute("DELETE FROM task_subtasks WHERE task_id = %s", (task_id,))
                cur.execute("DELETE FROM task_spirit WHERE task_id = %s", (task_id,))
                cur.execute("DELETE FROM task_labels WHERE task_id = %s", (task_id,))
                cur.execute(
                    "DELETE FROM task_dependencies WHERE task_id = %s OR depends_on_task_id = %s",
                    (task_id, task_id),
                )
                cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            conn.commit()
