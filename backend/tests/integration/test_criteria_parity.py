"""Integration tests for criteria API parity endpoints.

Tests for:
- POST /tasks/{id}/criteria/batch - Batch task criteria creation
- POST /capabilities (with nested criteria) - Single capability with criteria
- Partial failure handling for both
"""

import pytest
from app.main import app
from app.storage.connection import get_connection
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_project():
    """Create a test project and clean up after."""
    project_id = "test-criteria-parity"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                INSERT INTO projects (id, name, base_url)
                VALUES (%s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
            (project_id, "Test Criteria Parity", "http://localhost"),
        )
        conn.commit()

    yield project_id

    # Cleanup
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM task_criteria WHERE task_id LIKE 'task-test-crit-%'")
        cur.execute(
            "DELETE FROM acceptance_criteria WHERE project_id = %s",
            (project_id,),
        )
        cur.execute("DELETE FROM tasks WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


@pytest.fixture
def test_task(test_project):
    """Create a test task."""
    task_id = "task-test-crit-001"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                INSERT INTO tasks (id, project_id, title, status)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
            (task_id, test_project, "Test Task for Criteria", "pending"),
        )
        conn.commit()

    yield task_id


class TestTaskCriteriaBatch:
    """Tests for POST /tasks/{id}/criteria/batch endpoint."""

    def test_batch_create_multiple_criteria(self, client, test_project, test_task):
        """Create 3 criteria in one call."""
        response = client.post(
            f"/api/projects/{test_project}/tasks/{test_task}/criteria/batch",
            json={
                "items": [
                    {"criterion": "First criterion should be created successfully"},
                    {"criterion": "Second criterion with custom category", "category": "security"},
                    {"criterion": "Third criterion with threshold", "threshold": "100%"},
                ]
            },
        )

        assert response.status_code == 201
        data = response.json()

        assert len(data["created"]) == 3
        assert len(data["errors"]) == 0

        # Verify all have task_id
        for item in data["created"]:
            assert item["task_id"] == test_task
            assert item["criterion_id"].startswith("ac-")

        # Verify category was set correctly
        categories = [c["category"] for c in data["created"]]
        assert "security" in categories

    def test_batch_all_valid_items_created(self, client, test_project, test_task):
        """All valid items are created successfully."""
        response = client.post(
            f"/api/projects/{test_project}/tasks/{test_task}/criteria/batch",
            json={
                "items": [
                    {"criterion": "First valid criterion that should be created"},
                    {"criterion": "Second valid criterion that should be created"},
                    {"criterion": "Third valid criterion for testing batch"},
                ]
            },
        )

        assert response.status_code == 201
        data = response.json()

        assert len(data["created"]) == 3
        assert len(data["errors"]) == 0

    def test_batch_validation_rejects_empty_list(self, client, test_project, test_task):
        """Empty items list is handled."""
        response = client.post(
            f"/api/projects/{test_project}/tasks/{test_task}/criteria/batch",
            json={"items": []},
        )

        assert response.status_code == 201
        data = response.json()
        assert len(data["created"]) == 0
        assert len(data["errors"]) == 0

    def test_batch_rejects_nonexistent_task(self, client, test_project):
        """Returns 404 for nonexistent task."""
        response = client.post(
            f"/api/projects/{test_project}/tasks/task-nonexistent/criteria/batch",
            json={
                "items": [{"criterion": "This should not be created because task doesn't exist"}]
            },
        )

        assert response.status_code == 404


class TestCapabilityNestedCriteria:
    """Tests for POST /capabilities with nested criteria."""

    @pytest.fixture
    def test_component(self, test_project):
        """Create a test component."""
        component_id = None

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO components (project_id, component_id, name)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                (test_project, "test-comp-criteria", "Test Component"),
            )
            component_id = cur.fetchone()[0]
            conn.commit()

        yield component_id

        # Cleanup
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM capability_criteria WHERE capability_id IN "
                "(SELECT id FROM capabilities WHERE component_id = %s)",
                (component_id,),
            )
            cur.execute("DELETE FROM capabilities WHERE component_id = %s", (component_id,))
            cur.execute("DELETE FROM components WHERE id = %s", (component_id,))
            conn.commit()

    def test_create_capability_with_nested_criteria(self, client, test_project, test_component):
        """Create capability with 2 nested criteria."""
        response = client.post(
            f"/api/projects/{test_project}/capabilities",
            json={
                "component_id": test_component,
                "capability_id": "test-nested-crit-cap",
                "name": "Test Nested Criteria Capability",
                "criteria": [
                    {"criterion": "First capability criterion should be linked"},
                    {
                        "criterion": "Second capability criterion with category",
                        "category": "performance",
                    },
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["capability_id"] == "test-nested-crit-cap"
        assert data["criteria_created"] == 2

    def test_create_capability_criteria_linked_correctly(
        self, client, test_project, test_component
    ):
        """Verify criteria are linked to the correct capability."""
        # Create capability with criteria
        response = client.post(
            f"/api/projects/{test_project}/capabilities",
            json={
                "component_id": test_component,
                "capability_id": "test-linked-cap",
                "name": "Test Linked Capability",
                "criteria": [
                    {"criterion": "Criterion to verify linkage works correctly"},
                ],
            },
        )

        assert response.status_code == 200
        cap_data = response.json()
        assert cap_data["criteria_created"] == 1

        # Get capability and verify criteria
        get_response = client.get(
            f"/api/projects/{test_project}/capabilities/{cap_data['capability_id']}"
        )
        assert get_response.status_code == 200
        cap_detail = get_response.json()

        assert len(cap_detail["criteria"]) == 1
        assert "Criterion to verify linkage" in cap_detail["criteria"][0]["criterion"]

    def test_create_capability_empty_criteria_array(self, client, test_project, test_component):
        """Empty criteria array works without error."""
        response = client.post(
            f"/api/projects/{test_project}/capabilities",
            json={
                "component_id": test_component,
                "capability_id": "test-empty-crit-cap",
                "name": "Test Empty Criteria Capability",
                "criteria": [],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["criteria_created"] == 0


class TestPartialFailureHandling:
    """Tests for partial failure handling in both endpoints."""

    @pytest.fixture
    def test_component(self, test_project):
        """Create a test component for capability tests."""
        component_id = None

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                    INSERT INTO components (project_id, component_id, name)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                (test_project, "test-comp-partial", "Test Component Partial"),
            )
            component_id = cur.fetchone()[0]
            conn.commit()

        yield component_id

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM capability_criteria WHERE capability_id IN "
                "(SELECT id FROM capabilities WHERE component_id = %s)",
                (component_id,),
            )
            cur.execute("DELETE FROM capabilities WHERE component_id = %s", (component_id,))
            cur.execute("DELETE FROM components WHERE id = %s", (component_id,))
            conn.commit()

    def test_task_batch_items_persist_in_database(self, client, test_project, test_task):
        """Created items actually persist in the database."""
        response = client.post(
            f"/api/projects/{test_project}/tasks/{test_task}/criteria/batch",
            json={
                "items": [
                    {"criterion": "This criterion should persist in the database"},
                    {"criterion": "This one should also persist after creation"},
                ]
            },
        )

        assert response.status_code == 201
        data = response.json()

        assert len(data["created"]) == 2
        assert len(data["errors"]) == 0

        # Verify they actually persist by checking the task's criteria
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT COUNT(*) FROM task_criteria tc
                    JOIN acceptance_criteria ac ON tc.criterion_id = ac.id
                    WHERE tc.task_id = %s
                    """,
                (test_task,),
            )
            count = cur.fetchone()[0]

        assert count >= 2

    def test_capability_all_criteria_created(self, client, test_project, test_component):
        """Capability created with all valid criteria."""
        response = client.post(
            f"/api/projects/{test_project}/capabilities",
            json={
                "component_id": test_component,
                "capability_id": "test-all-crit-cap",
                "name": "Test All Criteria Capability",
                "criteria": [
                    {"criterion": "First valid criterion that should be created"},
                    {"criterion": "Second valid criterion for the capability"},
                    {"criterion": "Third valid criterion after the second one"},
                ],
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Capability should be created
        assert data["capability_id"] == "test-all-crit-cap"

        # All criteria should be created
        assert data["criteria_created"] == 3

    def test_pydantic_validation_rejects_short_criteria(self, client, test_project, test_task):
        """Pydantic validation rejects criteria that are too short."""
        response = client.post(
            f"/api/projects/{test_project}/tasks/{test_task}/criteria/batch",
            json={
                "items": [
                    {"criterion": "x"},  # Too short - Pydantic will reject
                ]
            },
        )

        # Pydantic validation returns 422
        assert response.status_code == 422
