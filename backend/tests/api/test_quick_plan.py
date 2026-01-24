"""Tests for quick_plan service and API endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.quick_plan import generate_plan, list_templates

client = TestClient(app)


class TestGeneratePlan:
    """Tests for the generate_plan service function."""

    def test_generate_plan_bug_fix(self):
        """Bug-fix template generates valid plan."""
        plan = generate_plan(
            title="Fix login bug",
            description="Fix the login validation issue",
            template="bug-fix",
        )
        assert plan["title"] == "Fix login bug"
        assert plan["objective"] == "Fix the login validation issue"
        assert plan["complexity"] == "SIMPLE"
        assert "subtasks" in plan
        assert len(plan["subtasks"]) >= 2

    def test_generate_plan_add_endpoint(self):
        """Add-endpoint template generates valid plan."""
        plan = generate_plan(
            title="Add user endpoint",
            description="Add GET /users endpoint",
            template="add-endpoint",
        )
        assert plan["title"] == "Add user endpoint"
        assert "subtasks" in plan

    def test_generate_plan_add_component(self):
        """Add-component template generates valid plan."""
        plan = generate_plan(
            title="Add navbar component",
            description="Add a navigation bar component",
            template="add-component",
        )
        assert plan["title"] == "Add navbar component"
        assert "subtasks" in plan

    def test_generate_plan_invalid_template(self):
        """Invalid template raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            generate_plan(
                title="Test",
                description="Test",
                template="invalid-template",
            )
        assert "Unknown template" in str(exc_info.value)

    def test_generate_plan_substitutes_params(self):
        """Parameters are substituted in templates."""
        plan = generate_plan(
            title="Fix specific bug",
            description="Fix the auth issue",
            template="bug-fix",
            params={"search_pattern": "auth_check", "target_file": "backend/app/auth.py"},
        )
        # Check that params were substituted in steps
        first_subtask = plan["subtasks"][0]
        first_step = first_subtask["steps"][0]
        assert "auth_check" in first_step["verify_command"]
        assert "backend/app/auth.py" in first_step["verify_command"]


class TestListTemplates:
    """Tests for list_templates function."""

    def test_list_templates_returns_all(self):
        """list_templates returns all available templates."""
        templates = list_templates()
        assert len(templates) == 3
        names = [t["name"] for t in templates]
        assert "bug-fix" in names
        assert "add-endpoint" in names
        assert "add-component" in names


class TestQuickPlanAPI:
    """Tests for POST /api/projects/{project}/tasks/quick-plan endpoint."""

    def test_quick_plan_endpoint(self):
        """Quick plan endpoint generates valid plan."""
        response = client.post(
            "/api/projects/summitflow/tasks/quick-plan",
            json={
                "title": "Test task",
                "description": "Test description",
                "template": "bug-fix",
                "params": {},
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Test task"
        assert "subtasks" in data

    def test_quick_plan_invalid_template(self):
        """Invalid template returns 400 error."""
        response = client.post(
            "/api/projects/summitflow/tasks/quick-plan",
            json={
                "title": "Test task",
                "description": "Test description",
                "template": "invalid",
                "params": {},
            },
        )
        assert response.status_code == 400
        assert "Unknown template" in response.json()["detail"]
