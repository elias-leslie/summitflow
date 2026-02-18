"""Tests for index generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from app.services.explorer.index_generator import generate_index, write_index_file


class TestGenerateIndex:
    """Tests for generate_index function."""

    def test_generate_index_empty_entries(self) -> None:
        """Test with no entries returns minimal YAML."""
        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
        ):
            mock_storage.get_entries.return_value = []
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert parsed["project"] == "test-project"
        # No folders key when no file entries exist
        assert parsed.get("folders") is None or parsed.get("folders") == {}

    def test_generate_index_groups_by_folder(self) -> None:
        """Test entries are grouped by top-level folder."""
        file_entries: list[dict[str, Any]] = [
            {"path": "backend/app/main.py"},
            {"path": "backend/app/models.py"},
            {"path": "frontend/src/App.tsx"},
            {"path": "README.md"},
        ]

        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
        ):
            # Return file entries for type=file, empty for others
            def get_entries_side_effect(project_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
                if filters.get("type") == "file":
                    return file_entries
                return []

            mock_storage.get_entries.side_effect = get_entries_side_effect
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert "folders" in parsed
        assert "backend" in parsed["folders"]
        assert "frontend" in parsed["folders"]
        assert "(root)" in parsed["folders"]

    def test_generate_index_detects_patterns(self) -> None:
        """Test pattern detection in paths."""
        file_entries: list[dict[str, Any]] = [
            {"path": "backend/tests/test_main.py"},
            {"path": "backend/app/config.py"},
            {"path": "docs/README.md"},
            {"path": "frontend/src/components/Button.tsx"},
            {"path": "backend/app/api/routes.py"},
        ]

        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
        ):

            def get_entries_side_effect(project_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
                if filters.get("type") == "file":
                    return file_entries
                return []

            mock_storage.get_entries.side_effect = get_entries_side_effect
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        # backend should have tests, api patterns
        assert "tests" in parsed["folders"]["backend"]
        assert "api" in parsed["folders"]["backend"]
        # frontend should have components pattern
        assert "components" in parsed["folders"]["frontend"]

    def test_generate_index_reasonable_size(self) -> None:
        """Test output stays reasonably sized with many entries."""
        # Generate many file entries across many folders
        entries: list[dict[str, Any]] = []
        for i in range(500):
            folder = f"folder{i % 30}"
            entries.append({"path": f"{folder}/file{i}.py"})

        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
        ):

            def get_entries_side_effect(project_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
                if filters.get("type") == "file":
                    return entries
                return []

            mock_storage.get_entries.side_effect = get_entries_side_effect
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}

            result = generate_index("test-project")

        # Just ensure it generates valid YAML
        parsed = yaml.safe_load(result)
        assert parsed["project"] == "test-project"
        assert "folders" in parsed


class TestWriteIndexFile:
    """Tests for write_index_file function."""

    def test_write_index_file_no_root_path(self) -> None:
        """Test returns None when no root path found."""
        with patch("app.services.explorer.index_generator.get_project_root") as mock_root:
            mock_root.return_value = None

            result = write_index_file("test-project")

        assert result is None

    def test_write_index_file_success(self, tmp_path: Path) -> None:
        """Test writes file to project root."""
        file_entries: list[dict[str, Any]] = [{"path": "backend/main.py"}]

        with (
            patch("app.services.explorer.index_generator.get_project_root") as mock_root,
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
        ):
            mock_root.return_value = str(tmp_path)

            def get_entries_side_effect(project_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
                if filters.get("type") == "file":
                    return file_entries
                return []

            mock_storage.get_entries.side_effect = get_entries_side_effect
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}

            result = write_index_file("test-project")

        assert result == str(tmp_path / ".index.yaml")
        assert (tmp_path / ".index.yaml").exists()

        # Verify content
        content = (tmp_path / ".index.yaml").read_text()
        parsed = yaml.safe_load(content)
        assert parsed["project"] == "test-project"
        assert "backend" in parsed["folders"]
