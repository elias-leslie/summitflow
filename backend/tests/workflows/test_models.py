"""Tests for Hatchet workflow input models."""

from __future__ import annotations

from app.workflows.models import ProjectInput


class TestProjectInput:
    """Tests for ProjectInput model, especially None-input handling."""

    def test_default_project_id(self) -> None:
        """Empty dict input should use default project_id."""
        model = ProjectInput()
        assert model.project_id == "summitflow"

    def test_explicit_project_id(self) -> None:
        model = ProjectInput(project_id="agent-hub")
        assert model.project_id == "agent-hub"

    def test_none_input_uses_defaults(self) -> None:
        """Hatchet cron may pass None — model_validator handles it."""
        model = ProjectInput.model_validate(None)
        assert model.project_id == "summitflow"

    def test_empty_dict_input(self) -> None:
        model = ProjectInput.model_validate({})
        assert model.project_id == "summitflow"

    def test_dict_with_project_id(self) -> None:
        model = ProjectInput.model_validate({"project_id": "test-project"})
        assert model.project_id == "test-project"
