"""Tests for dependency scanner standalone project detection.

Tests verify multi-context discovery:
1. Standalone project (no workspace) is detected correctly
2. Workspace member is NOT treated as standalone
3. Project with own lockfile is treated as standalone even in workspace
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.explorer.types import dependencies_nodejs
from app.services.explorer.types.dependencies_browser_runtime import (
    scan_browser_runtime_dependencies,
)
from app.services.explorer.types.dependencies_nodejs import scan_nodejs_dependencies
from app.services.explorer.types.dependencies_python import (
    _package_list_cmd,
    scan_python_dependencies,
)


class TestStandaloneProjectDetection:
    """Test multi-context discovery for standalone vs workspace projects."""

    @pytest.fixture
    def root_path(self) -> Path:
        """Create a mock project root."""
        return Path("/fake/project")

    def test_standalone_project_no_workspace(self, root_path: Path) -> None:
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

    def test_workspace_member_not_standalone(self, root_path: Path) -> None:
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

    def test_project_with_own_lockfile_treated_as_standalone(self, root_path: Path) -> None:
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

    def test_mixed_parent_directory_scenario(self, root_path: Path) -> None:
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


def test_workspace_root_scans_root_and_member_manifests(tmp_path: Path) -> None:
    root = tmp_path
    (root / "pnpm-workspace.yaml").write_text("packages:\n  - frontend\n")
    (root / "package.json").write_text('{"dependencies":{"root-package":"1.0.0"}}')
    frontend = root / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"devDependencies":{"frontend-package":"2.0.0"}}')
    (root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\npackages:\n  'root-package@1.0.0': {}\n  'frontend-package@2.0.0': {}\n")
    with (
        patch("app.services.explorer.types.dependencies_nodejs._run_pnpm_audit", return_value=({}, "unknown")) as audit,
        patch("app.services.explorer.types.dependencies_nodejs._run_pnpm_outdated", return_value={}) as outdated,
    ):
        entries = scan_nodejs_dependencies("test-project", root)
    assert {entry.name for entry in entries} == {"root-package", "frontend-package"}
    audit.assert_called_once_with(root)
    outdated.assert_called_once_with(root)


@pytest.fixture
def local_node_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if local inventory attempts online enrichment or subprocesses."""
    monkeypatch.setattr(dependencies_nodejs, "MONOREPO_ROOT", Path("/missing-workspace"))
    monkeypatch.setattr(
        dependencies_nodejs.safe_subprocess, "run",
        MagicMock(side_effect=AssertionError("local inventory must not run subprocesses")),
    )


def _node_manifest(root: Path, dependency: str = "next") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "package.json"
    manifest.write_text(json.dumps({"dependencies": {dependency: "^15.0.0"}}))
    return manifest


def test_node_inventory_preserves_standalone_root(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    manifest = _node_manifest(tmp_path)
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [(entry.name, entry.path) for entry in entries] == [("next", "nodejs/next")]
    assert entries[0].metadata["source_file"] == str(manifest)


def test_node_inventory_discovers_frontend_without_root_manifest(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    frontend = tmp_path / "frontend"
    manifest = _node_manifest(frontend)
    (frontend / "pnpm-lock.yaml").write_text(
        "packages:\n  next@15.0.3: {}\n  scheduler@0.25.0: {}\n"
    )
    _node_manifest(frontend / "node_modules" / "next")
    (frontend / "node_modules" / "next" / "package.json").write_text('{"version":"15.0.2"}')
    with (
        patch.object(dependencies_nodejs, "_run_pnpm_audit", return_value=({}, "unknown")),
        patch.object(dependencies_nodejs, "_run_pnpm_outdated", return_value={}),
    ):
        entries = scan_nodejs_dependencies("test-project", tmp_path)
    by_name = {entry.name: entry for entry in entries}
    assert by_name["next"].path == "nodejs/frontend/next"
    assert by_name["next"].metadata["source_file"] == str(manifest)
    assert by_name["next"].metadata["locked_version"] == "15.0.3"
    assert by_name["next"].metadata["installed_version"] == "15.0.2"
    assert by_name["next"].metadata["audit_check_status"] == "unknown"
    assert by_name["scheduler"].path == "nodejs/frontend/transitive/scheduler"


@pytest.mark.parametrize("workspace_format", ["pnpm", "npm", "yarn"])
def test_node_inventory_discovers_declared_workspaces(
    tmp_path: Path, local_node_inventory: None, workspace_format: str,
) -> None:
    root_manifest = _node_manifest(tmp_path, "root-dependency")
    _node_manifest(tmp_path / "apps" / "zebra", "zebra-dependency")
    _node_manifest(tmp_path / "apps" / "alpha", "alpha-dependency")
    if workspace_format == "pnpm":
        (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - apps/*\n")
    else:
        payload = json.loads(root_manifest.read_text())
        payload["workspaces"] = ["apps/*"] if workspace_format == "npm" else {"packages": ["apps/*"]}
        root_manifest.write_text(json.dumps(payload))
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert {entry.name for entry in entries} == {
        "root-dependency", "alpha-dependency", "zebra-dependency",
    }
    assert [entry.path for entry in entries] == sorted(entry.path for entry in entries)


def test_node_inventory_uses_configured_frontend_path(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    _node_manifest(tmp_path / "clients" / "browser")
    (tmp_path / "project.identity.json").write_text(json.dumps({
        "project": {"id": "test-project"}, "runtime": {"frontend_dir": "clients/browser"},
    }))
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.path for entry in entries] == ["nodejs/clients/browser/next"]


@pytest.mark.parametrize(
    "ignored", ["node_modules", "vendor", "dist", "build", ".cache", "references", "source-lab"],
)
def test_node_inventory_prunes_ignored_directories(
    tmp_path: Path, local_node_inventory: None, ignored: str,
) -> None:
    _node_manifest(tmp_path / "frontend")
    _node_manifest(tmp_path / ignored, "ignored-direct")
    _node_manifest(tmp_path / ignored / "nested", "ignored-nested")
    (tmp_path / "pnpm-workspace.yaml").write_text(f"packages:\n  - '*'\n  - '{ignored}/*'\n")
    real_scandir = os.scandir

    def guarded_scandir(directory: Path | str):
        assert ignored not in Path(directory).relative_to(tmp_path).parts
        return real_scandir(directory)

    with patch("os.scandir", guarded_scandir):
        entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.name for entry in entries] == ["next"]


def test_node_inventory_deduplicates_overlapping_workspace_manifests(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    _node_manifest(tmp_path, "root-dependency")
    _node_manifest(tmp_path / "frontend")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - frontend\n  - './frontend'\n  - '*'\n  - '.'\n"
    )
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert len(entries) == 2
    assert len({entry.path for entry in entries}) == 2


def test_node_inventory_keeps_same_dependency_in_distinct_apps(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    _node_manifest(tmp_path / "frontend")
    _node_manifest(tmp_path / "admin")
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.path for entry in entries] == ["nodejs/admin/next", "nodejs/frontend/next"]


def test_node_inventory_without_manifests_is_empty(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    (tmp_path / "backend").mkdir()
    assert scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False) == []


def test_node_inventory_rejects_workspace_escape_and_symlink(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    root = tmp_path / "project"
    _node_manifest(root / "frontend")
    _node_manifest(tmp_path / "outside", "outside-dependency")
    (root / "linked").symlink_to(tmp_path / "outside", target_is_directory=True)
    (root / "pnpm-workspace.yaml").write_text(
        "packages:\n  - frontend\n  - '../outside'\n  - linked\n"
    )
    entries = scan_nodejs_dependencies("test-project", root, include_network_checks=False)
    assert [entry.name for entry in entries] == ["next"]


def test_node_inventory_recursive_declarations_have_depth_and_visit_bounds(
    tmp_path: Path, local_node_inventory: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _node_manifest(tmp_path, "root-dependency")
    _node_manifest(tmp_path / "apps" / "alpha", "alpha-dependency")
    _node_manifest(tmp_path / "apps" / "nested" / "deeper", "deep-dependency")
    _node_manifest(tmp_path / "source-lab" / "sample", "lab-dependency")
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - '**'\n")
    monkeypatch.setattr(dependencies_nodejs, "_MAX_WORKSPACE_DEPTH", 2)
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert {entry.name for entry in entries} == {"root-dependency", "alpha-dependency"}
    monkeypatch.setattr(dependencies_nodejs, "_MAX_WORKSPACE_DIRECTORIES", 2)
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.name for entry in entries] == ["root-dependency"]


def test_node_inventory_honors_workspace_exclusions(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    _node_manifest(tmp_path, "root-dependency")
    _node_manifest(tmp_path / "apps" / "frontend")
    _node_manifest(tmp_path / "apps" / "example", "example-dependency")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - apps/*\n  - '!apps/example'\n"
    )
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert {entry.name for entry in entries} == {"root-dependency", "next"}


def test_node_inventory_does_not_confuse_project_path_prefixes(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    root = tmp_path / "app"
    root.mkdir()
    _node_manifest(tmp_path / "app-other", "other-project-dependency")
    (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - app-other\n")
    assert scan_nodejs_dependencies("test-project", root, include_network_checks=False) == []


def test_node_inventory_tolerates_invalid_discovery_configuration(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    _node_manifest(tmp_path / "frontend")
    (tmp_path / "package.json").write_text('{"workspaces":null}')
    (tmp_path / "pnpm-workspace.yaml").write_text("packages: [invalid\n")
    (tmp_path / "project.identity.json").write_text("invalid")
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.name for entry in entries] == ["next"]


def test_node_child_discovery_bounds_enumeration_and_stat_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dependencies_nodejs, "_MAX_WORKSPACE_DIRECTORIES", 2)
    enumerated: list[int] = []

    def directory_entries():
        for index in range(1000):
            enumerated.append(index)
            yield SimpleNamespace(path=str(tmp_path / f"app-{index}"))

    scanner = MagicMock()
    scanner.__enter__.return_value = directory_entries()
    with (
        patch("os.scandir", return_value=scanner),
        patch.object(dependencies_nodejs, "_safe_node_directory", return_value=True) as safe,
        patch.object(Path, "is_dir", return_value=True) as stat,
    ):
        directories = dependencies_nodejs._node_child_directories(tmp_path, tmp_path)
    assert directories == []
    assert enumerated == [0, 1]
    assert safe.call_count == 0
    assert stat.call_count == 0


@pytest.mark.parametrize("manifest_name", ["package.json", "pnpm-workspace.yaml"])
def test_node_inventory_never_reads_rejected_workspace_manifests(
    tmp_path: Path, local_node_inventory: None, manifest_name: str,
) -> None:
    root = tmp_path / "project"
    frontend = root / "frontend"
    frontend.mkdir(parents=True)
    outside = tmp_path / "outside" / manifest_name
    outside.parent.mkdir()
    outside.write_text('{"workspaces":[]}' if manifest_name == "package.json" else "packages: []\n")
    (frontend / manifest_name).symlink_to(outside)
    real_read_text = Path.read_text

    def contained_read_text(path: Path, *args, **kwargs):
        assert path.resolve().is_relative_to(root), f"read escaped manifest: {path}"
        return real_read_text(path, *args, **kwargs)

    with patch.object(Path, "read_text", contained_read_text):
        assert scan_nodejs_dependencies("test-project", root, include_network_checks=False) == []


@pytest.mark.parametrize("workspace_format", ["npm", "yarn"])
def test_node_child_discovery_honors_declared_workspace_exclusions(
    tmp_path: Path, local_node_inventory: None, workspace_format: str,
) -> None:
    manifest = _node_manifest(tmp_path, "root-dependency")
    _node_manifest(tmp_path / "frontend")
    _node_manifest(tmp_path / "example", "excluded-dependency")
    payload = json.loads(manifest.read_text())
    patterns = ["*", "!example"]
    payload["workspaces"] = patterns if workspace_format == "npm" else {"packages": patterns}
    manifest.write_text(json.dumps(payload))
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert {entry.name for entry in entries} == {"root-dependency", "next"}


def test_node_child_discovery_preserves_undeclared_safe_apps(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    manifest = _node_manifest(tmp_path, "root-dependency")
    _node_manifest(tmp_path / "frontend")
    _node_manifest(tmp_path / "example", "excluded-dependency")
    payload = json.loads(manifest.read_text())
    payload["workspaces"] = ["packages/*", "!example"]
    manifest.write_text(json.dumps(payload))
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert {entry.name for entry in entries} == {"root-dependency", "next"}


@pytest.mark.parametrize("limit", [2, 3, 4])
def test_node_child_membership_is_independent_of_enumeration_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, limit: int,
) -> None:
    monkeypatch.setattr(dependencies_nodejs, "_MAX_WORKSPACE_DIRECTORIES", limit)
    for name in ("a", "b", "z"):
        (tmp_path / name).mkdir()
    results: list[list[Path]] = []
    with patch.object(dependencies_nodejs.logger, "warning") as warning:
        for order in [("a", "z", "b"), ("b", "a", "z")]:
            scanner = MagicMock()
            scanner.__enter__.return_value = iter(
                SimpleNamespace(path=str(tmp_path / name)) for name in order
            )
            with patch("os.scandir", return_value=scanner):
                results.append(dependencies_nodejs._node_child_directories(tmp_path, tmp_path))
    assert warning.call_count == (2 if limit <= 3 else 0)
    assert results[0] == results[1]
    expected = [tmp_path / name for name in ("a", "b", "z")] if limit > 3 else []
    assert results[0] == expected


def test_node_fallback_honors_pnpm_exclusions_without_root_manifest(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    _node_manifest(tmp_path / "frontend")
    _node_manifest(tmp_path / "example", "excluded-dependency")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "packages:\n  - packages/*\n  - '!example'\n"
    )
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.name for entry in entries] == ["next"]


def test_node_nested_app_merges_package_and_pnpm_workspace_patterns(
    tmp_path: Path, local_node_inventory: None,
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "package.json").write_text('{"workspaces":["libs/*"]}')
    (app / "pnpm-workspace.yaml").write_text("packages:\n  - tools/cli\n  - '!libs/legacy'\n")
    _node_manifest(app / "libs/current", "current-dependency")
    _node_manifest(app / "libs/legacy", "legacy-dependency")
    _node_manifest(app / "tools/cli", "cli-dependency")
    entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert {entry.name for entry in entries} == {"current-dependency", "cli-dependency"}


@pytest.mark.parametrize("discovery", ["identity", "npm-literal", "pnpm-literal"])
def test_node_discovery_retains_explicit_paths_when_child_listing_is_ambiguous(
    tmp_path: Path, local_node_inventory: None,
    monkeypatch: pytest.MonkeyPatch, discovery: str,
) -> None:
    monkeypatch.setattr(dependencies_nodejs, "_MAX_WORKSPACE_DIRECTORIES", 2)
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    _node_manifest(tmp_path / "frontend")
    if discovery == "identity":
        (tmp_path / "project.identity.json").write_text(json.dumps({
            "project": {"id": "test-project"}, "runtime": {"frontend_dir": "frontend"},
        }))
    elif discovery == "npm-literal":
        (tmp_path / "package.json").write_text('{"workspaces":["*","frontend"]}')
    else:
        (tmp_path / "pnpm-workspace.yaml").write_text("packages:\n  - '*'\n  - frontend\n")
    real_scandir = os.scandir

    def ordered_scandir(directory: Path | str):
        if Path(directory) != tmp_path:
            return real_scandir(directory)
        scanner = MagicMock()
        scanner.__enter__.return_value = iter(
            SimpleNamespace(path=str(tmp_path / name)) for name in ("a", "b", "frontend")
        )
        return scanner

    with patch("os.scandir", ordered_scandir):
        entries = scan_nodejs_dependencies("test-project", tmp_path, include_network_checks=False)
    assert [entry.path for entry in entries] == ["nodejs/frontend/next"]


def test_python_scan_uses_manifest_local_environment(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi>=0.115"]\n')
    python = backend / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    with (
        patch("app.services.explorer.types.dependencies_python._run_python_audit", return_value=({}, "unknown")),
        patch("app.services.explorer.types.dependencies_python._run_python_outdated", return_value={}),
        patch("app.services.explorer.types.dependencies_python._run_python_installed", return_value={"fastapi": "0.136.3"}) as installed,
    ):
        entries = scan_python_dependencies("test-project", tmp_path)
    installed.assert_called_once_with(backend)
    assert entries[0].metadata["installed_version"] == "0.136.3"


def test_python_package_listing_uses_uv_for_pipless_venv(tmp_path: Path) -> None:
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    with patch("app.services.explorer.types.dependencies_python.shutil.which", return_value="/usr/bin/uv"):
        command = _package_list_cmd(tmp_path)
    assert command == [
        "/usr/bin/uv", "pip", "list", "--python", str(python),
        "--format", "json", "--no-python-downloads",
    ]


def test_browser_runtime_scan_ingests_versioned_owner_inventory(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1, "owner": "browser-automation", "scope": "local-host",
        "runtimes": [{
            "id": "agent-browser", "executable": "/usr/bin/agent-browser",
            "installed_version": "0.26.0", "installed_status": "observed",
            "latest_version": None, "latest_status": "unchecked",
            "recommended_version": None, "recommended_status": "unchecked",
        }],
    }
    with (
        patch("app.services.explorer.types.dependencies_browser_runtime.shutil.which", return_value="/usr/bin/st"),
        patch("app.services.explorer.types.dependencies_browser_runtime.safe_subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload))) as run,
    ):
        entries = scan_browser_runtime_dependencies("browser-automation", tmp_path)
    run.assert_called_once()
    assert entries[0].path == "browser-runtime/agent-browser"
    assert entries[0].metadata["installed_version"] == "0.26.0"
    assert entries[0].metadata["latest_check_status"] == "unknown"


def test_other_projects_do_not_probe_browser_owner(tmp_path: Path) -> None:
    with patch("app.services.explorer.types.dependencies_browser_runtime.safe_subprocess.run") as run:
        assert scan_browser_runtime_dependencies("summitflow", tmp_path) == []
    run.assert_not_called()
