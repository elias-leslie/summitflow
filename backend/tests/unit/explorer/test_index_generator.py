"""Tests for index generator."""

from unittest.mock import patch

import yaml

from app.services.explorer.index_generator import generate_index, write_index_file


class TestGenerateIndex:
    """Tests for generate_index function."""

    def test_generate_index_empty_entries(self):
        """Test with no entries returns minimal YAML."""
        with patch("app.services.explorer.index_generator.storage") as mock_storage:
            mock_storage.get_entries.return_value = []

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert parsed["project"] == "test-project"
        assert parsed["folders"] == {}

    def test_generate_index_groups_by_folder(self):
        """Test entries are grouped by top-level folder."""
        entries = [
            {"path": "backend/app/main.py"},
            {"path": "backend/app/models.py"},
            {"path": "frontend/src/App.tsx"},
            {"path": "README.md"},
        ]

        with patch("app.services.explorer.index_generator.storage") as mock_storage:
            mock_storage.get_entries.return_value = entries

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert parsed["total_files"] == 4
        assert "backend" in parsed["folders"]
        assert "frontend" in parsed["folders"]
        assert "(root)" in parsed["folders"]

    def test_generate_index_detects_patterns(self):
        """Test pattern detection in paths."""
        entries = [
            {"path": "backend/tests/test_main.py"},
            {"path": "backend/app/config.py"},
            {"path": "docs/README.md"},
            {"path": "frontend/src/components/Button.tsx"},
            {"path": "backend/app/api/routes.py"},
        ]

        with patch("app.services.explorer.index_generator.storage") as mock_storage:
            mock_storage.get_entries.return_value = entries

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        # backend should have tests, config, api patterns
        assert "tests" in parsed["folders"]["backend"]
        # docs folder has docs pattern
        assert "docs" in parsed["folders"]["docs"]

    def test_generate_index_under_100_lines(self):
        """Test output stays under 100 lines constraint."""
        # Generate many entries across many folders
        entries = []
        for i in range(500):
            folder = f"folder{i % 30}"
            entries.append({"path": f"{folder}/file{i}.py"})

        with patch("app.services.explorer.index_generator.storage") as mock_storage:
            mock_storage.get_entries.return_value = entries

            result = generate_index("test-project")

        lines = result.strip().split("\n")
        assert len(lines) < 100, f"Index has {len(lines)} lines, expected <100"


class TestWriteIndexFile:
    """Tests for write_index_file function."""

    def test_write_index_file_no_root_path(self):
        """Test returns None when no root path found."""
        with patch("app.services.explorer.index_generator.get_project_root") as mock_root:
            mock_root.return_value = None

            result = write_index_file("test-project")

        assert result is None

    def test_write_index_file_success(self, tmp_path):
        """Test writes file to project root."""
        entries = [{"path": "backend/main.py"}]

        with (
            patch("app.services.explorer.index_generator.get_project_root") as mock_root,
            patch("app.services.explorer.index_generator.storage") as mock_storage,
        ):
            mock_root.return_value = str(tmp_path)
            mock_storage.get_entries.return_value = entries

            result = write_index_file("test-project")

        assert result == str(tmp_path / ".index.yaml")
        assert (tmp_path / ".index.yaml").exists()

        # Verify content
        content = (tmp_path / ".index.yaml").read_text()
        parsed = yaml.safe_load(content)
        assert parsed["project"] == "test-project"
        assert "backend" in parsed["folders"]
