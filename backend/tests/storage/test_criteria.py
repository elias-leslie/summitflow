"""Tests for the criteria storage module."""

import pytest
from app.storage import criteria
from app.storage.connection import get_connection


@pytest.fixture
def conn():
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn):
    """Fixture to clean up test project data after tests."""
    project_id = "test-criteria-project"

    # Setup: ensure project exists
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Criteria Project", "http://localhost"),
        )
        conn.commit()

    yield project_id

    # Cleanup: remove test data
    with conn.cursor() as cur:
        cur.execute("DELETE FROM acceptance_criteria WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


class TestCriterionIdGeneration:
    """Tests for get_next_criterion_id."""

    def test_first_criterion_returns_ac_001(self, conn, cleanup_project):
        """First criterion in a project should be ac-001."""
        project_id = cleanup_project
        result = criteria.get_next_criterion_id(conn, project_id)
        assert result == "ac-001"

    def test_increment_criterion_id(self, conn, cleanup_project):
        """Second criterion should increment the number."""
        project_id = cleanup_project

        # Create first criterion
        criteria.create_criterion(conn, project_id, "First criterion test")

        # Next should be ac-002
        result = criteria.get_next_criterion_id(conn, project_id)
        assert result == "ac-002"

    def test_multi_project_isolation(self, conn, cleanup_project):
        """Criterion IDs should be isolated per project."""
        project_id = cleanup_project
        other_project = "test-criteria-other"

        # Ensure other project exists
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (other_project, "Other Project", "http://other"),
            )
            conn.commit()

        try:
            # Create criteria in main project
            criteria.create_criterion(conn, project_id, "Project A criterion 1")
            criteria.create_criterion(conn, project_id, "Project A criterion 2")

            # Other project should still start at ac-001
            result = criteria.get_next_criterion_id(conn, other_project)
            assert result == "ac-001"
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM acceptance_criteria WHERE project_id = %s", (other_project,)
                )
                cur.execute("DELETE FROM projects WHERE id = %s", (other_project,))
                conn.commit()


class TestCriterionCRUD:
    """Tests for create, get, delete operations."""

    def test_create_criterion(self, conn, cleanup_project):
        """Create criterion with auto-generated ID."""
        project_id = cleanup_project
        result = criteria.create_criterion(
            conn,
            project_id,
            "User can login with valid credentials",
            category="correctness",
            measurement="test",
            threshold=None,
            created_by_task_id="task-123",
        )

        assert result["criterion_id"] == "ac-001"
        assert result["criterion"] == "User can login with valid credentials"
        assert result["category"] == "correctness"
        assert result["created_by_task_id"] == "task-123"

    def test_get_criterion_by_criterion_id(self, conn, cleanup_project):
        """Get criterion by project + criterion_id string."""
        project_id = cleanup_project
        created = criteria.create_criterion(conn, project_id, "Test criterion")

        result = criteria.get_criterion(conn, project_id, created["criterion_id"])
        assert result is not None
        assert result["id"] == created["id"]
        assert result["criterion"] == "Test criterion"

    def test_get_criterion_by_id(self, conn, cleanup_project):
        """Get criterion by internal database ID."""
        project_id = cleanup_project
        created = criteria.create_criterion(conn, project_id, "Test by ID")

        result = criteria.get_criterion_by_id(conn, created["id"])
        assert result is not None
        assert result["criterion_id"] == created["criterion_id"]

    def test_get_nonexistent_criterion(self, conn, cleanup_project):
        """Get returns None for nonexistent criterion."""
        result = criteria.get_criterion(conn, cleanup_project, "ac-999")
        assert result is None

    def test_delete_criterion(self, conn, cleanup_project):
        """Delete criterion by database ID."""
        project_id = cleanup_project
        created = criteria.create_criterion(conn, project_id, "To delete")

        deleted = criteria.delete_criterion(conn, created["id"])
        assert deleted is True

        result = criteria.get_criterion_by_id(conn, created["id"])
        assert result is None


class TestCapabilityCriteriaJunction:
    """Tests for capability-criteria linking."""

    @pytest.fixture
    def capability(self, conn, cleanup_project):
        """Create a test capability."""
        project_id = cleanup_project

        # Create component first
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO components (project_id, component_id, name)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (project_id, "test-component", "Test Component"),
            )
            component_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO capabilities (project_id, component_id, capability_id, name)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (project_id, component_id, "test-cap", "Test Capability"),
            )
            capability_id = cur.fetchone()[0]
            conn.commit()

        yield {"id": capability_id, "capability_id": "test-cap"}

        # Cleanup
        with conn.cursor() as cur:
            cur.execute("DELETE FROM capabilities WHERE id = %s", (capability_id,))
            cur.execute("DELETE FROM components WHERE id = %s", (component_id,))
            conn.commit()

    def test_link_criterion_to_capability(self, conn, cleanup_project, capability):
        """Link a criterion to a capability."""
        project_id = cleanup_project
        crit = criteria.create_criterion(conn, project_id, "Cap criterion")

        result = criteria.link_criterion_to_capability(conn, capability["id"], crit["id"])
        assert result is True

        # Verify via get_criteria_for_capability
        linked = criteria.get_criteria_for_capability(conn, project_id, capability["capability_id"])
        assert len(linked) == 1
        assert linked[0]["criterion_id"] == crit["criterion_id"]

    def test_unlink_criterion_with_orphan_cleanup(self, conn, cleanup_project, capability):
        """Unlink criterion and verify orphan is deleted."""
        project_id = cleanup_project
        crit = criteria.create_criterion(conn, project_id, "Orphan test criterion")

        criteria.link_criterion_to_capability(conn, capability["id"], crit["id"])
        criteria.unlink_criterion_from_capability(conn, capability["id"], crit["id"])

        # Criterion should be deleted (orphaned)
        result = criteria.get_criterion_by_id(conn, crit["id"])
        assert result is None


class TestTaskCriteriaJunction:
    """Tests for task-criteria linking."""

    @pytest.fixture
    def task(self, conn, cleanup_project):
        """Create a test task."""
        project_id = cleanup_project
        task_id = "task-test-criteria"

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tasks (id, project_id, title, status)
                VALUES (%s, %s, %s, %s)
                """,
                (task_id, project_id, "Test Task", "pending"),
            )
            conn.commit()

        yield task_id

        with conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            conn.commit()

    def test_link_criterion_to_task(self, conn, cleanup_project, task):
        """Link a criterion to a task."""
        project_id = cleanup_project
        crit = criteria.create_criterion(conn, project_id, "Task criterion")

        result = criteria.link_criterion_to_task(conn, task, crit["id"])
        assert result is True

        linked = criteria.get_criteria_for_task(conn, project_id, task)
        assert len(linked) == 1
        assert linked[0]["verified"] is False

    def test_update_task_criterion_verification(self, conn, cleanup_project, task):
        """Update verification status for task criterion."""
        project_id = cleanup_project
        crit = criteria.create_criterion(conn, project_id, "Verify test")
        criteria.link_criterion_to_task(conn, task, crit["id"])

        result = criteria.update_task_criterion_verification(conn, task, crit["id"], True, "test")
        assert result is True

        linked = criteria.get_criteria_for_task(conn, project_id, task)
        assert linked[0]["verified"] is True
        assert linked[0]["verified_by"] == "test"


class TestCriterionTestsJunction:
    """Tests for criterion-tests linking."""

    @pytest.fixture
    def test_record(self, conn, cleanup_project):
        """Create a test record."""
        project_id = cleanup_project

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tests (project_id, test_id, name, test_type)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (project_id, "test-login", "test_login_success", "pytest"),
            )
            test_id = cur.fetchone()[0]
            conn.commit()

        yield test_id

        with conn.cursor() as cur:
            cur.execute("DELETE FROM tests WHERE id = %s", (test_id,))
            conn.commit()

    def test_link_test_to_criterion(self, conn, cleanup_project, test_record):
        """Link a test to a criterion."""
        project_id = cleanup_project
        crit = criteria.create_criterion(conn, project_id, "Test-linked criterion")

        result = criteria.link_test_to_criterion(conn, crit["id"], test_record, is_primary=True)
        assert result is True

        tests = criteria.get_tests_for_criterion(conn, crit["id"])
        assert len(tests) == 1
        assert tests[0]["is_primary"] is True

    def test_get_criteria_for_test(self, conn, cleanup_project, test_record):
        """Get all criteria verified by a test."""
        project_id = cleanup_project
        crit1 = criteria.create_criterion(conn, project_id, "Criterion 1")
        crit2 = criteria.create_criterion(conn, project_id, "Criterion 2")

        criteria.link_test_to_criterion(conn, crit1["id"], test_record)
        criteria.link_test_to_criterion(conn, crit2["id"], test_record)

        result = criteria.get_criteria_for_test(conn, test_record)
        assert len(result) == 2

    def test_unlink_test_from_criterion(self, conn, cleanup_project, test_record):
        """Unlink a test from a criterion."""
        project_id = cleanup_project
        crit = criteria.create_criterion(conn, project_id, "Unlink test")
        criteria.link_test_to_criterion(conn, crit["id"], test_record)

        result = criteria.unlink_test_from_criterion(conn, crit["id"], test_record)
        assert result is True

        tests = criteria.get_tests_for_criterion(conn, crit["id"])
        assert len(tests) == 0
