"""Dependency scanner for Explorer.

Scans Python (pyproject.toml, uv.lock) and Node.js (package.json, pnpm-lock.yaml)
dependencies across the monorepo. Includes security audit and outdated checks.

Metadata schema:
{
  "package_type": "python" | "nodejs",
  "constraint": ">=1.0.0",
  "locked_version": "1.2.3",
  "latest_version": "1.5.0",
  "is_outdated": true,
  "is_workspace_ref": false,
  "is_dev_dependency": false,
  "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
  "audit_advisories": ["CVE-2024-XXXX: Description..."],
  "source_file": "/path/to/pyproject.toml"
}
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..base import BaseScanner, get_project_root
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

# Monorepo root for pnpm workspace
MONOREPO_ROOT = Path("/home/kasadis")

# Known dependency config files
PYTHON_CONFIGS = ["pyproject.toml", "requirements.txt", "setup.py"]
NODE_CONFIGS = ["package.json"]


class DependencyScanner(BaseScanner):
    """Scans project dependencies for explorer entries."""

    entry_type = "dependency"

    def __init__(self, project_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(project_id, config)
        self.root_path: Path | None = None
        self._audit_cache: dict[str, dict[str, Any]] = {}  # Cache audit results per project type

    def scan(self) -> list[ExplorerEntryCreate]:
        """Scan dependencies and return entries."""
        root = get_project_root(self.project_id)
        if not root:
            logger.error(f"No root_path configured for project {self.project_id}")
            return []

        self.root_path = Path(root)
        if not self.root_path.exists():
            logger.error(f"Root path does not exist: {self.root_path}")
            return []

        logger.info(f"Dependency scan started for {self.project_id}: {self.root_path}")

        entries: list[ExplorerEntryCreate] = []

        # Scan Python dependencies
        python_entries = self._scan_python_dependencies()
        entries.extend(python_entries)

        # Scan Node.js dependencies
        node_entries = self._scan_nodejs_dependencies()
        entries.extend(node_entries)

        logger.info(
            f"Dependency scan found {len(entries)} entries "
            f"({len(python_entries)} Python, {len(node_entries)} Node.js)"
        )
        return entries

    # -------------------------------------------------------------------------
    # Python Dependency Scanning
    # -------------------------------------------------------------------------

    def _scan_python_dependencies(self) -> list[ExplorerEntryCreate]:
        """Scan Python dependencies from pyproject.toml and uv.lock."""
        entries: list[ExplorerEntryCreate] = []
        assert self.root_path is not None

        # Find pyproject.toml files
        pyproject_files = list(self.root_path.rglob("pyproject.toml"))
        # Filter out reference/vendor directories
        pyproject_files = [
            p for p in pyproject_files
            if "references" not in str(p) and "node_modules" not in str(p)
            and ".venv" not in str(p)
        ]

        # Run pip-audit once for the project if available
        audit_results = self._run_python_audit()
        outdated_results = self._run_python_outdated()

        for pyproject_path in pyproject_files:
            try:
                deps = self._parse_pyproject_toml(pyproject_path)
                lock_versions = self._parse_uv_lock(pyproject_path.parent / "uv.lock")

                for name, constraint in deps.items():
                    is_dev = constraint.get("dev", False)
                    version_constraint = constraint.get("version", "")

                    # Get locked version if available
                    locked_version = lock_versions.get(name)

                    # Check if outdated
                    outdated_info = outdated_results.get(name, {})
                    latest_version = outdated_info.get("latest")
                    is_outdated = outdated_info.get("outdated", False)

                    # Check vulnerabilities
                    vuln_info = audit_results.get(name, {})

                    # Build metadata
                    metadata = {
                        "package_type": "python",
                        "constraint": version_constraint,
                        "locked_version": locked_version,
                        "latest_version": latest_version,
                        "is_outdated": is_outdated,
                        "is_workspace_ref": "file://" in version_constraint,
                        "is_dev_dependency": is_dev,
                        "vulnerabilities": vuln_info.get("vulnerabilities", {
                            "critical": 0, "high": 0, "medium": 0, "low": 0
                        }),
                        "audit_advisories": vuln_info.get("advisories", []),
                        "source_file": str(pyproject_path),
                    }

                    # Determine health
                    health = self._calculate_dependency_health(metadata)

                    # Path format: python/{source_dir}/{package_name}
                    rel_source = pyproject_path.parent.relative_to(self.root_path)
                    path = f"python/{rel_source}/{name}"

                    entries.append(ExplorerEntryCreate(
                        path=path,
                        name=name,
                        health_status=health,
                        metadata=metadata,
                    ))

            except Exception as e:
                logger.warning(f"Failed to parse {pyproject_path}: {e}")

        return entries

    def _parse_pyproject_toml(self, path: Path) -> dict[str, dict[str, Any]]:
        """Parse pyproject.toml and extract dependencies.

        Returns dict of package_name -> {version, dev}.
        """
        dependencies: dict[str, dict[str, Any]] = {}
        try:
            content = path.read_text()

            # Parse main dependencies
            in_deps = False
            in_dev_deps = False
            current_section = ""

            for line in content.splitlines():
                stripped = line.strip()

                # Track sections
                if stripped.startswith("["):
                    in_deps = False
                    in_dev_deps = False
                    if stripped == "dependencies = [" or "dependencies]" in stripped:
                        in_deps = True
                        current_section = "main"
                    elif "dev" in stripped.lower() and "dependencies" in stripped.lower():
                        in_dev_deps = True
                        current_section = "dev"
                    continue

                if stripped.startswith("dependencies = ["):
                    in_deps = True
                    current_section = "main"
                    continue

                if in_deps or in_dev_deps:
                    if stripped.startswith("]"):
                        in_deps = False
                        in_dev_deps = False
                        continue

                    # Parse dependency line: "package>=1.0.0" or "package[extra]>=1.0.0"
                    # Also handle: package = ">=1.0.0" format
                    match = re.match(
                        r'["\']?([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?([<>=!~^][^"\']*)?["\']?',
                        stripped
                    )
                    if match:
                        pkg_name = match.group(1).lower().replace("_", "-")
                        version = match.group(2) or ""
                        dependencies[pkg_name] = {
                            "version": version.strip(),
                            "dev": current_section == "dev",
                        }

        except Exception as e:
            logger.warning(f"Failed to parse pyproject.toml {path}: {e}")

        return dependencies

    def _parse_uv_lock(self, path: Path) -> dict[str, str]:
        """Parse uv.lock file for exact locked versions.

        Returns dict of package_name -> locked_version.
        """
        versions: dict[str, str] = {}
        if not path.exists():
            return versions

        try:
            content = path.read_text()
            # uv.lock format: [[package]]\nname = "pkg"\nversion = "1.2.3"
            current_name = None
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith('name = "'):
                    current_name = stripped.split('"')[1].lower().replace("_", "-")
                elif stripped.startswith('version = "') and current_name:
                    version = stripped.split('"')[1]
                    versions[current_name] = version
                    current_name = None

        except Exception as e:
            logger.warning(f"Failed to parse uv.lock {path}: {e}")

        return versions

    def _run_python_audit(self) -> dict[str, dict[str, Any]]:
        """Run pip-audit and return vulnerability info by package."""
        results: dict[str, dict[str, Any]] = {}
        assert self.root_path is not None

        try:
            # Try pip-audit first
            venv_path = self.root_path / ".venv" / "bin" / "pip-audit"
            if venv_path.exists():
                cmd = [str(venv_path), "--format", "json"]
            else:
                # Fall back to system pip-audit
                cmd = ["pip-audit", "--format", "json"]

            proc = subprocess.run(
                cmd,
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if proc.stdout:
                audit_data = json.loads(proc.stdout)
                for vuln in audit_data.get("vulnerabilities", []):
                    pkg = vuln.get("name", "").lower().replace("_", "-")
                    if pkg not in results:
                        results[pkg] = {
                            "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                            "advisories": [],
                        }

                    # Categorize severity
                    severity = vuln.get("severity", "unknown").lower()
                    if severity in results[pkg]["vulnerabilities"]:
                        results[pkg]["vulnerabilities"][severity] += 1

                    # Add advisory
                    advisory = f"{vuln.get('id', 'Unknown')}: {vuln.get('description', '')[:100]}"
                    results[pkg]["advisories"].append(advisory)

        except FileNotFoundError:
            logger.info("pip-audit not available, skipping Python security scan")
        except subprocess.TimeoutExpired:
            logger.warning("pip-audit timed out")
        except Exception as e:
            logger.warning(f"pip-audit failed: {e}")

        return results

    def _run_python_outdated(self) -> dict[str, dict[str, Any]]:
        """Check for outdated Python packages."""
        results: dict[str, dict[str, Any]] = {}
        assert self.root_path is not None

        try:
            venv_pip = self.root_path / ".venv" / "bin" / "pip"
            if venv_pip.exists():
                cmd = [str(venv_pip), "list", "--outdated", "--format", "json"]
            else:
                cmd = ["pip", "list", "--outdated", "--format", "json"]

            proc = subprocess.run(
                cmd,
                cwd=self.root_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if proc.stdout:
                outdated = json.loads(proc.stdout)
                for pkg in outdated:
                    name = pkg.get("name", "").lower().replace("_", "-")
                    results[name] = {
                        "latest": pkg.get("latest_version"),
                        "current": pkg.get("version"),
                        "outdated": True,
                    }

        except Exception as e:
            logger.warning(f"pip outdated check failed: {e}")

        return results

    # -------------------------------------------------------------------------
    # Node.js Dependency Scanning
    # -------------------------------------------------------------------------

    def _scan_nodejs_dependencies(self) -> list[ExplorerEntryCreate]:
        """Scan Node.js dependencies from pnpm workspace."""
        entries: list[ExplorerEntryCreate] = []
        assert self.root_path is not None

        # Check if this project is part of pnpm workspace
        workspace_root = self._find_pnpm_workspace_root()
        if not workspace_root:
            # Check for standalone package.json
            package_json = self.root_path / "package.json"
            if package_json.exists():
                return self._scan_standalone_node_project(package_json)
            return entries

        # Parse workspace structure
        workspace_packages = self._parse_pnpm_workspace(workspace_root)
        lock_versions = self._parse_pnpm_lock(workspace_root / "pnpm-lock.yaml")

        # Run pnpm audit once
        audit_results = self._run_pnpm_audit(workspace_root)
        outdated_results = self._run_pnpm_outdated(workspace_root)

        # Scan each package.json that belongs to this project
        for pkg_path in workspace_packages:
            if not str(pkg_path).startswith(str(self.root_path)):
                continue  # Skip packages outside this project

            try:
                deps = self._parse_package_json(pkg_path)

                for name, info in deps.items():
                    constraint = info.get("version", "")
                    is_dev = info.get("dev", False)
                    is_workspace = "workspace:" in constraint

                    # Resolve version from lock file
                    locked_version = lock_versions.get(name)

                    # Check outdated
                    outdated_info = outdated_results.get(name, {})
                    latest_version = outdated_info.get("latest")
                    is_outdated = outdated_info.get("outdated", False)

                    # Check vulnerabilities
                    vuln_info = audit_results.get(name, {})

                    metadata = {
                        "package_type": "nodejs",
                        "constraint": constraint,
                        "locked_version": locked_version,
                        "latest_version": latest_version,
                        "is_outdated": is_outdated,
                        "is_workspace_ref": is_workspace,
                        "is_dev_dependency": is_dev,
                        "vulnerabilities": vuln_info.get("vulnerabilities", {
                            "critical": 0, "high": 0, "medium": 0, "low": 0
                        }),
                        "audit_advisories": vuln_info.get("advisories", []),
                        "source_file": str(pkg_path),
                    }

                    health = self._calculate_dependency_health(metadata)

                    # Path format: nodejs/{package_dir}/{dep_name}
                    rel_source = pkg_path.parent.relative_to(self.root_path)
                    path = f"nodejs/{rel_source}/{name}"

                    entries.append(ExplorerEntryCreate(
                        path=path,
                        name=name,
                        health_status=health,
                        metadata=metadata,
                    ))

            except Exception as e:
                logger.warning(f"Failed to parse {pkg_path}: {e}")

        return entries

    def _find_pnpm_workspace_root(self) -> Path | None:
        """Find pnpm-workspace.yaml by walking up from project root."""
        assert self.root_path is not None
        current = self.root_path

        # Walk up to find workspace root (max 5 levels)
        for _ in range(5):
            workspace_file = current / "pnpm-workspace.yaml"
            if workspace_file.exists():
                return current
            if current.parent == current:
                break
            current = current.parent

        # Check known monorepo root
        if (MONOREPO_ROOT / "pnpm-workspace.yaml").exists():
            return MONOREPO_ROOT

        return None

    def _parse_pnpm_workspace(self, workspace_root: Path) -> list[Path]:
        """Parse pnpm-workspace.yaml and return package.json paths."""
        packages: list[Path] = []
        workspace_file = workspace_root / "pnpm-workspace.yaml"

        try:
            content = workspace_file.read_text()
            # Simple YAML parsing for packages list
            in_packages = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped == "packages:":
                    in_packages = True
                    continue
                if in_packages:
                    if stripped.startswith("-"):
                        # Extract glob pattern
                        pattern = stripped.lstrip("- ").strip("'\"")
                        # Resolve glob
                        if "*" in pattern:
                            # Handle glob patterns like "agent-hub/packages/*"
                            base, glob_part = pattern.rsplit("/", 1)
                            base_path = workspace_root / base
                            if base_path.exists():
                                for match in base_path.glob(glob_part):
                                    pkg_json = match / "package.json"
                                    if pkg_json.exists():
                                        packages.append(pkg_json)
                        else:
                            pkg_json = workspace_root / pattern / "package.json"
                            if pkg_json.exists():
                                packages.append(pkg_json)
                    elif not stripped.startswith("#") and stripped:
                        # End of packages section
                        break

        except Exception as e:
            logger.warning(f"Failed to parse pnpm-workspace.yaml: {e}")

        return packages

    def _parse_pnpm_lock(self, path: Path) -> dict[str, str]:
        """Parse pnpm-lock.yaml for locked versions.

        Returns dict of package_name -> locked_version.
        """
        versions: dict[str, str] = {}
        if not path.exists():
            return versions

        try:
            content = path.read_text()
            # pnpm-lock.yaml format varies, but generally:
            # packages:
            #   /package@version:
            # or in newer formats:
            #   'package@version':
            for line in content.splitlines():
                # Match patterns like: '/fastapi@0.115.0:' or 'react@19.2.3:'
                match = re.match(r"['\"]?/?([^@]+)@([^:'\"]+)", line.strip())
                if match:
                    name = match.group(1)
                    version = match.group(2)
                    # Skip if it looks like a URL or complex specifier
                    if "/" not in name and not version.startswith("http"):
                        versions[name] = version

        except Exception as e:
            logger.warning(f"Failed to parse pnpm-lock.yaml: {e}")

        return versions

    def _parse_package_json(self, path: Path) -> dict[str, dict[str, Any]]:
        """Parse package.json and extract dependencies.

        Returns dict of package_name -> {version, dev}.
        """
        dependencies: dict[str, dict[str, Any]] = {}

        try:
            content = json.loads(path.read_text())

            # Main dependencies
            for name, version in content.get("dependencies", {}).items():
                dependencies[name] = {"version": version, "dev": False}

            # Dev dependencies
            for name, version in content.get("devDependencies", {}).items():
                dependencies[name] = {"version": version, "dev": True}

            # Peer dependencies (mark separately)
            for name, version in content.get("peerDependencies", {}).items():
                if name not in dependencies:
                    dependencies[name] = {"version": version, "dev": False, "peer": True}

        except Exception as e:
            logger.warning(f"Failed to parse package.json {path}: {e}")

        return dependencies

    def _scan_standalone_node_project(self, package_json: Path) -> list[ExplorerEntryCreate]:
        """Scan a standalone Node.js project (not in pnpm workspace)."""
        entries: list[ExplorerEntryCreate] = []

        try:
            deps = self._parse_package_json(package_json)

            for name, info in deps.items():
                metadata = {
                    "package_type": "nodejs",
                    "constraint": info.get("version", ""),
                    "locked_version": None,
                    "latest_version": None,
                    "is_outdated": False,
                    "is_workspace_ref": False,
                    "is_dev_dependency": info.get("dev", False),
                    "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                    "audit_advisories": [],
                    "source_file": str(package_json),
                }

                entries.append(ExplorerEntryCreate(
                    path=f"nodejs/{name}",
                    name=name,
                    health_status="unknown",
                    metadata=metadata,
                ))

        except Exception as e:
            logger.warning(f"Failed to scan standalone Node project: {e}")

        return entries

    def _run_pnpm_audit(self, workspace_root: Path) -> dict[str, dict[str, Any]]:
        """Run pnpm audit and return vulnerability info by package."""
        results: dict[str, dict[str, Any]] = {}

        try:
            proc = subprocess.run(
                ["pnpm", "audit", "--json"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if proc.stdout:
                try:
                    audit_data = json.loads(proc.stdout)
                    # pnpm audit JSON format
                    advisories = audit_data.get("advisories", {})
                    for _id, advisory in advisories.items():
                        pkg = advisory.get("module_name", "")
                        if pkg not in results:
                            results[pkg] = {
                                "vulnerabilities": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                                "advisories": [],
                            }

                        severity = advisory.get("severity", "unknown").lower()
                        if severity in results[pkg]["vulnerabilities"]:
                            results[pkg]["vulnerabilities"][severity] += 1

                        adv_text = f"{advisory.get('cves', ['Unknown'])[0] if advisory.get('cves') else 'Unknown'}: {advisory.get('title', '')[:100]}"
                        results[pkg]["advisories"].append(adv_text)
                except json.JSONDecodeError:
                    # pnpm audit might output non-JSON on success
                    pass

        except FileNotFoundError:
            logger.info("pnpm not available, skipping Node.js security scan")
        except subprocess.TimeoutExpired:
            logger.warning("pnpm audit timed out")
        except Exception as e:
            logger.warning(f"pnpm audit failed: {e}")

        return results

    def _run_pnpm_outdated(self, workspace_root: Path) -> dict[str, dict[str, Any]]:
        """Check for outdated Node.js packages."""
        results: dict[str, dict[str, Any]] = {}

        try:
            proc = subprocess.run(
                ["pnpm", "outdated", "--json"],
                cwd=workspace_root,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if proc.stdout:
                try:
                    outdated = json.loads(proc.stdout)
                    # pnpm outdated JSON format: {pkg: {current, latest, wanted}}
                    for pkg, info in outdated.items():
                        results[pkg] = {
                            "latest": info.get("latest"),
                            "current": info.get("current"),
                            "wanted": info.get("wanted"),
                            "outdated": True,
                        }
                except json.JSONDecodeError:
                    pass

        except Exception as e:
            logger.warning(f"pnpm outdated check failed: {e}")

        return results

    # -------------------------------------------------------------------------
    # Health Calculation
    # -------------------------------------------------------------------------

    def _calculate_dependency_health(self, metadata: dict[str, Any]) -> str:
        """Calculate health status based on vulnerabilities and outdated status."""
        vulns = metadata.get("vulnerabilities", {})
        critical = vulns.get("critical", 0)
        high = vulns.get("high", 0)
        medium = vulns.get("medium", 0)

        # Critical or high vulnerabilities = error
        if critical > 0 or high > 0:
            return "error"

        # Medium vulnerabilities or significantly outdated = warning
        if medium > 0:
            return "warning"

        # Outdated but no vulns = warning
        if metadata.get("is_outdated", False):
            return "warning"

        return "healthy"

    def get_health_status(self, entry: ExplorerEntryCreate) -> str:
        """Override to use dependency-specific health calculation."""
        return self._calculate_dependency_health(entry.metadata)
