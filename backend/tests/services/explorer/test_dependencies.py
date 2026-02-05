"""Tests for dependency scanner standalone project detection.

Tests verify multi-context discovery:
1. Standalone project (no workspace) is detected correctly
2. Workspace member is NOT treated as standalone
3. Project with own lockfile is treated as standalone even in workspace
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.explorer.types.dependencies_nodejs import scan_nodejs_dependencies


class TestStandaloneProjectDetection:
    """Test multi-context discovery for standalone vs workspace projects."""

    @pytest.fixture
    def root_path(self):
        """Create a mock project root."""
        return Path("/fake/project")

    def test_standalone_project_no_workspace(self, root_path):
        """Standalone project without workspace should be detected correctly."""
        # Patch the functions in dependencies_nodejs module
        with (
            patch(
                "app.services.explorer.types.dependencies_nodejs._find_pnpm_workspace_root",
                return_value=None,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._scan_standalone_node_project"
            ) as mock_scan,
            patch("pathlib.Path.exists", return_value=True),
        ):
            mock_scan.return_value = [
                MagicMock(
                    entry_type="dependency",
                    name="express",
                    path="nodejs/express",
                )
            ]

            # Should call standalone scanner when no workspace found
            result = scan_nodejs_dependencies("test-project", root_path)

            mock_scan.assert_called_once()
            assert len(result) == 1

    def test_workspace_member_not_standalone(self, root_path):
        """Workspace member should NOT be treated as standalone."""
        workspace_root = Path("/fake/workspace")
        workspace_packages = [
            Path("/fake/project/package.json"),  # This project IS in workspace
            Path("/fake/other-project/package.json"),
        ]

        with (
            patch(
                "app.services.explorer.types.dependencies_nodejs._find_pnpm_workspace_root",
                return_value=workspace_root,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._parse_pnpm_workspace",
                return_value=workspace_packages,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._has_own_lockfile",
                return_value=False,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._is_project_in_workspace",
                return_value=True,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._parse_pnpm_lock", return_value={}
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._run_pnpm_audit", return_value={}
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._run_pnpm_outdated",
                return_value={},
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._scan_standalone_node_project"
            ) as mock_standalone,
        ):
            # Should NOT call standalone scanner
            scan_nodejs_dependencies("test-project", root_path)

            mock_standalone.assert_not_called()

    def test_project_with_own_lockfile_treated_as_standalone(self, root_path):
        """Project with own lockfile should be standalone even if workspace exists."""
        workspace_root = Path("/fake/workspace")
        workspace_packages = [
            Path("/fake/other-project/package.json"),  # This project NOT in workspace
        ]

        with (
            patch(
                "app.services.explorer.types.dependencies_nodejs._find_pnpm_workspace_root",
                return_value=workspace_root,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._parse_pnpm_workspace",
                return_value=workspace_packages,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._has_own_lockfile",
                return_value=True,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._is_project_in_workspace",
                return_value=False,
            ),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "app.services.explorer.types.dependencies_nodejs._scan_standalone_node_project"
            ) as mock_standalone,
        ):
            mock_standalone.return_value = []

            # Should call standalone scanner when has own lockfile
            scan_nodejs_dependencies("test-project", root_path)

            mock_standalone.assert_called_once()

    def test_mixed_parent_directory_scenario(self, root_path):
        """Project should correctly identify when it has own resolution context.

        Scenario: Workspace at parent level but project has own lockfile.
        """
        workspace_root = Path("/fake")  # Workspace at parent level
        workspace_packages = [
            Path("/fake/frontend/package.json"),
            Path("/fake/backend/package.json"),
        ]

        # _is_project_in_workspace checks if root_path matches any workspace package
        # /fake/project is NOT in [/fake/frontend, /fake/backend]
        with (
            patch(
                "app.services.explorer.types.dependencies_nodejs._find_pnpm_workspace_root",
                return_value=workspace_root,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._parse_pnpm_workspace",
                return_value=workspace_packages,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._has_own_lockfile",
                return_value=True,
            ),
            patch(
                "app.services.explorer.types.dependencies_nodejs._is_project_in_workspace",
                return_value=False,
            ),
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "app.services.explorer.types.dependencies_nodejs._scan_standalone_node_project"
            ) as mock_standalone,
        ):
            mock_standalone.return_value = [
                MagicMock(
                    entry_type="dependency",
                    name="react",
                    path="nodejs/react",
                )
            ]

            result = scan_nodejs_dependencies("test-project", root_path)

            # Should be treated as standalone
            mock_standalone.assert_called_once()
            assert len(result) == 1
