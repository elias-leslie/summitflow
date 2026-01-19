"""Tests for dependency scanner standalone project detection.

Tests verify multi-context discovery:
1. Standalone project (no workspace) is detected correctly
2. Workspace member is NOT treated as standalone
3. Project with own lockfile is treated as standalone even in workspace
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.explorer.types.dependencies import DependencyScanner


class TestStandaloneProjectDetection:
    """Test multi-context discovery for standalone vs workspace projects."""

    @pytest.fixture
    def scanner(self):
        """Create a scanner with mocked project root."""
        scanner = DependencyScanner("test-project")
        scanner.root_path = Path("/fake/project")
        return scanner

    def test_standalone_project_no_workspace(self, scanner):
        """Standalone project without workspace should be detected correctly."""
        with patch.object(scanner, "_find_pnpm_workspace_root", return_value=None):
            with patch.object(scanner, "_scan_standalone_node_project") as mock_scan:
                with patch("pathlib.Path.exists", return_value=True):
                    mock_scan.return_value = [
                        MagicMock(
                            entry_type="dependency",
                            name="express",
                            path="nodejs/express",
                        )
                    ]

                    # Should call standalone scanner when no workspace found
                    result = scanner._scan_nodejs_dependencies()

                    mock_scan.assert_called_once()
                    assert len(result) == 1

    def test_workspace_member_not_standalone(self, scanner):
        """Workspace member should NOT be treated as standalone."""
        workspace_root = Path("/fake/workspace")
        workspace_packages = [
            Path("/fake/project/package.json"),  # This project IS in workspace
            Path("/fake/other-project/package.json"),
        ]

        with patch.object(scanner, "_find_pnpm_workspace_root", return_value=workspace_root):
            with patch.object(scanner, "_parse_pnpm_workspace", return_value=workspace_packages):
                with patch.object(scanner, "_has_own_lockfile", return_value=False):
                    with patch.object(scanner, "_is_project_in_workspace", return_value=True):
                        with patch.object(scanner, "_parse_pnpm_lock", return_value={}):
                            with patch.object(scanner, "_run_pnpm_audit", return_value={}):
                                with patch.object(scanner, "_run_pnpm_outdated", return_value={}):
                                    with patch.object(
                                        scanner, "_scan_standalone_node_project"
                                    ) as mock_standalone:
                                        # Should NOT call standalone scanner
                                        scanner._scan_nodejs_dependencies()

                                        mock_standalone.assert_not_called()

    def test_project_with_own_lockfile_treated_as_standalone(self, scanner):
        """Project with own lockfile should be standalone even if workspace exists."""
        workspace_root = Path("/fake/workspace")
        workspace_packages = [
            Path("/fake/other-project/package.json"),  # This project NOT in workspace
        ]

        with patch.object(scanner, "_find_pnpm_workspace_root", return_value=workspace_root):
            with patch.object(scanner, "_parse_pnpm_workspace", return_value=workspace_packages):
                with patch.object(scanner, "_has_own_lockfile", return_value=True):
                    with patch.object(scanner, "_is_project_in_workspace", return_value=False):
                        with patch("pathlib.Path.exists", return_value=True):
                            with patch.object(
                                scanner, "_scan_standalone_node_project"
                            ) as mock_standalone:
                                mock_standalone.return_value = []

                                # Should call standalone scanner when has own lockfile
                                scanner._scan_nodejs_dependencies()

                                mock_standalone.assert_called_once()

    def test_mixed_parent_directory_scenario(self, scanner):
        """Project should correctly identify when it has own resolution context.

        Scenario: Workspace at parent level but project has own lockfile.
        """
        workspace_root = Path("/fake")  # Workspace at parent level
        workspace_packages = [
            Path("/fake/frontend/package.json"),
            Path("/fake/backend/package.json"),
        ]
        # Scanner root is /fake/project which is NOT in the packages list
        scanner.root_path = Path("/fake/project")

        with patch.object(scanner, "_find_pnpm_workspace_root", return_value=workspace_root):
            with patch.object(scanner, "_parse_pnpm_workspace", return_value=workspace_packages):
                with patch.object(scanner, "_has_own_lockfile", return_value=True):
                    # _is_project_in_workspace checks if root_path matches any workspace package
                    # /fake/project is NOT in [/fake/frontend, /fake/backend]
                    with patch.object(scanner, "_is_project_in_workspace", return_value=False):
                        with patch("pathlib.Path.exists", return_value=True):
                            with patch.object(
                                scanner, "_scan_standalone_node_project"
                            ) as mock_standalone:
                                mock_standalone.return_value = [
                                    MagicMock(
                                        entry_type="dependency",
                                        name="react",
                                        path="nodejs/react",
                                    )
                                ]

                                result = scanner._scan_nodejs_dependencies()

                                # Should be treated as standalone
                                mock_standalone.assert_called_once()
                                assert len(result) == 1
