"""Tests for index generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from app.services.explorer.index_generator import generate_index, get_network_info, write_index_file


class TestGenerateIndex:
    """Tests for generate_index function."""

    def test_generate_index_empty_entries(self) -> None:
        """Test with no entries returns minimal YAML."""
        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
        ):
            mock_storage.get_entries.return_value = []
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}
            mock_urls.return_value = {}
            mock_network.return_value = {}
            mock_explorer.return_value = {}

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
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
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
            mock_urls.return_value = {}
            mock_network.return_value = {}
            mock_explorer.return_value = {}

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
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
        ):

            def get_entries_side_effect(project_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
                if filters.get("type") == "file":
                    return file_entries
                return []

            mock_storage.get_entries.side_effect = get_entries_side_effect
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}
            mock_urls.return_value = {}
            mock_network.return_value = {}
            mock_explorer.return_value = {}

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
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
        ):

            def get_entries_side_effect(project_id: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
                if filters.get("type") == "file":
                    return entries
                return []

            mock_storage.get_entries.side_effect = get_entries_side_effect
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}
            mock_urls.return_value = {}
            mock_network.return_value = {}
            mock_explorer.return_value = {}

            result = generate_index("test-project")

        # Just ensure it generates valid YAML
        parsed = yaml.safe_load(result)
        assert parsed["project"] == "test-project"
        assert "folders" in parsed

    def test_generate_index_includes_urls_and_explorer_summary(self) -> None:
        """Test derived URLs and explorer trust metadata are surfaced."""
        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
        ):
            mock_storage.get_entries.return_value = []
            mock_env.return_value = {}
            mock_services.return_value = {"backend_port": 8001, "frontend_port": 3001}
            mock_cli.return_value = {}
            mock_urls.return_value = {
                "frontend": "http://localhost:3001",
                "api": "http://localhost:8001/api",
            }
            mock_network.return_value = {}
            mock_explorer.return_value = {
                "scan_status": "completed",
                "last_completed_scan": "2026-03-11T12:00:00+00:00",
                "entry_counts": {"file": 12, "page": 2},
                "symbol_count": 44,
                "stale_metadata_count": 3,
            }

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert parsed["urls"]["frontend"] == "http://localhost:3001"
        assert parsed["urls"]["api"] == "http://localhost:8001/api"
        assert parsed["explorer"]["scan_status"] == "completed"
        assert parsed["explorer"]["symbol_count"] == 44
        assert parsed["explorer"]["entry_counts"] == {"file": 12, "page": 2}

    def test_generate_index_excludes_stale_neo4j_infrastructure(self) -> None:
        """Test generated index only includes active shared infrastructure ports."""
        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
        ):
            mock_storage.get_entries.return_value = []
            mock_env.return_value = {}
            mock_services.return_value = {
                "backend_port": 8001,
                "frontend_port": 3001,
                "infrastructure": {"postgres": 5432, "redis": 6379},
            }
            mock_cli.return_value = {}
            mock_urls.return_value = {}
            mock_network.return_value = {}
            mock_explorer.return_value = {}

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert parsed["services"]["infrastructure"] == {"postgres": 5432, "redis": 6379}
        assert "neo4j" not in parsed["services"]["infrastructure"]


class TestGetProjectUrls:
    """Tests for get_project_urls function."""

    def test_port_derived_url_takes_precedence_over_base_url(self) -> None:
        """Port-derived localhost URL should win over stale base_url."""
        from app.services.explorer.index_generator import get_project_urls

        with (
            patch("app.services.explorer.base.get_project_config") as mock_config,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
        ):
            mock_config.return_value = {"base_url": "http://192.168.8.233:8000"}
            mock_services.return_value = {"backend_port": 8000, "frontend_port": 3000}

            urls = get_project_urls("portfolio-ai")

        assert urls["frontend"] == "http://localhost:3000"
        assert urls["api"] == "http://localhost:8000/api"

    def test_base_url_used_when_no_frontend_port(self) -> None:
        """base_url should be used as fallback when frontend_port is missing."""
        from app.services.explorer.index_generator import get_project_urls

        with (
            patch("app.services.explorer.base.get_project_config") as mock_config,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
        ):
            mock_config.return_value = {"base_url": "https://example.com"}
            mock_services.return_value = {"backend_port": 8000}

            urls = get_project_urls("test-project")

        assert urls["frontend"] == "https://example.com"
        assert urls["api"] == "http://localhost:8000/api"


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
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
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
            mock_urls.return_value = {}
            mock_network.return_value = {}
            mock_explorer.return_value = {}

            result = write_index_file("test-project")

        assert result == str(tmp_path / ".index.yaml")
        assert (tmp_path / ".index.yaml").exists()

        # Verify content
        content = (tmp_path / ".index.yaml").read_text()
        parsed = yaml.safe_load(content)
        assert parsed["project"] == "test-project"
        assert "backend" in parsed["folders"]


class TestGetNetworkInfo:
    """Tests for get_network_info function."""

    def test_returns_host_ip_and_hostname(self) -> None:
        """Test successful hostname -I and socket.gethostname."""
        import subprocess as sp

        mock_result = sp.CompletedProcess(args=[], returncode=0, stdout="192.168.8.244 172.17.0.1\n")
        with (
            patch("app.services.explorer.index_generator.subprocess.run", return_value=mock_result),
            patch("app.services.explorer.index_generator.socket.gethostname", return_value="summitflow-prod"),
        ):
            info = get_network_info()

        assert info["host_ip"] == "192.168.8.244"
        assert info["hostname"] == "summitflow-prod"

    def test_returns_empty_on_failure(self) -> None:
        """Test graceful degradation when commands fail."""
        with (
            patch("app.services.explorer.index_generator.subprocess.run", side_effect=OSError),
            patch("app.services.explorer.index_generator.socket.gethostname", side_effect=OSError),
        ):
            info = get_network_info()

        assert info == {}

    def test_network_info_included_in_generated_index(self) -> None:
        """Test network section appears in generated YAML."""
        with (
            patch("app.services.explorer.index_generator.storage") as mock_storage,
            patch("app.services.explorer.index_generator.get_environment") as mock_env,
            patch("app.services.explorer.index_generator.get_services") as mock_services,
            patch("app.services.explorer.index_generator.get_cli_info") as mock_cli,
            patch("app.services.explorer.index_generator.get_project_urls") as mock_urls,
            patch("app.services.explorer.index_generator.get_network_info") as mock_network,
            patch("app.services.explorer.index_generator.get_explorer_summary") as mock_explorer,
        ):
            mock_storage.get_entries.return_value = []
            mock_env.return_value = {}
            mock_services.return_value = {}
            mock_cli.return_value = {}
            mock_urls.return_value = {}
            mock_network.return_value = {"host_ip": "10.0.0.1", "hostname": "test-host"}
            mock_explorer.return_value = {}

            result = generate_index("test-project")

        parsed = yaml.safe_load(result)
        assert parsed["network"]["host_ip"] == "10.0.0.1"
        assert parsed["network"]["hostname"] == "test-host"
