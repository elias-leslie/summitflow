"""Node.js dependency scanning for Explorer.

Handles parsing of package.json, pnpm-lock.yaml files, workspace detection,
and running pnpm audit and outdated checks.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

# Monorepo root for pnpm workspace
MONOREPO_ROOT = Path("/home/kasadis")


def scan_nodejs_dependencies(
    project_id: str,
    root_path: Path,
) -> list[ExplorerEntryCreate]:
    """Scan Node.js dependencies using multi-context discovery.

    Strategy:
    1. Check if project is part of pnpm workspace
    2. If workspace found but project NOT in workspace packages, check for own lockfile
    3. Projects with own lockfile are treated as standalone (resolution boundary)
    4. Otherwise scan workspace packages that belong to this project

    Args:
        project_id: Project identifier for logging
        root_path: Root path to search for Node.js dependency files

    Returns:
        List of explorer entries for Node.js dependencies
    """
    entries: list[ExplorerEntryCreate] = []

    # Check if this project is part of pnpm workspace
    workspace_root = _find_pnpm_workspace_root(root_path)

    if not workspace_root:
        # No workspace found - scan standalone
        logger.debug(f"No pnpm workspace found, scanning {project_id} as standalone")
        package_json = root_path / "package.json"
        if package_json.exists():
            return _scan_standalone_node_project(package_json)
        return entries

    # Workspace found - check if project is actually IN the workspace
    workspace_packages = _parse_pnpm_workspace(workspace_root)
    is_in_workspace = _is_project_in_workspace(root_path, workspace_packages)

    # Check if project has its own lockfile (resolution boundary)
    has_own_lockfile = _has_own_lockfile(root_path)

    if not is_in_workspace or has_own_lockfile:
        # Project is standalone even though workspace exists nearby
        logger.info(
            f"Project {project_id} has own resolution context "
            f"(in_workspace={is_in_workspace}, own_lockfile={has_own_lockfile}), "
            "scanning as standalone"
        )
        package_json = root_path / "package.json"
        if package_json.exists():
            return _scan_standalone_node_project(package_json)
        return entries

    # Project is part of workspace - use workspace scanning
    logger.debug(f"Scanning {project_id} as part of pnpm workspace at {workspace_root}")
    lock_versions = _parse_pnpm_lock(workspace_root / "pnpm-lock.yaml")

    # Run pnpm audit once
    audit_results = _run_pnpm_audit(workspace_root)
    outdated_results = _run_pnpm_outdated(workspace_root)

    # Scan each package.json that belongs to this project
    for pkg_path in workspace_packages:
        if not str(pkg_path).startswith(str(root_path)):
            continue  # Skip packages outside this project

        try:
            deps = _parse_package_json(pkg_path)

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
                    "vulnerabilities": vuln_info.get(
                        "vulnerabilities", {"critical": 0, "high": 0, "medium": 0, "low": 0}
                    ),
                    "audit_advisories": vuln_info.get("advisories", []),
                    "source_file": str(pkg_path),
                }

                health = calculate_health_for_entry("dependency", metadata)

                # Path format: nodejs/{package_dir}/{dep_name}
                rel_source = pkg_path.parent.relative_to(root_path)
                path = f"nodejs/{rel_source}/{name}"

                entries.append(
                    ExplorerEntryCreate(
                        path=path,
                        name=name,
                        health_status=health,
                        metadata=metadata,
                    )
                )

        except Exception as e:
            logger.warning(f"Failed to parse {pkg_path}: {e}")

    return entries


def _find_pnpm_workspace_root(root_path: Path) -> Path | None:
    """Find pnpm-workspace.yaml by walking up from project root."""
    current = root_path

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


def _is_project_in_workspace(root_path: Path, workspace_packages: list[Path]) -> bool:
    """Check if any workspace package is under this project's root."""
    project_root_str = str(root_path)
    return any(str(pkg_path).startswith(project_root_str) for pkg_path in workspace_packages)


def _has_own_lockfile(root_path: Path) -> bool:
    """Check if project has its own lockfile (resolution boundary).

    Projects with their own lockfile should be scanned as standalone,
    even if they're under a workspace directory structure.
    """
    lockfile_names = ["pnpm-lock.yaml", "package-lock.json", "yarn.lock", "bun.lockb"]
    return any((root_path / lockfile).exists() for lockfile in lockfile_names)


def _parse_pnpm_workspace(workspace_root: Path) -> list[Path]:
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


def _parse_pnpm_lock(path: Path) -> dict[str, str]:
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


def _parse_package_json(path: Path) -> dict[str, dict[str, Any]]:
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


def _scan_standalone_node_project(package_json: Path) -> list[ExplorerEntryCreate]:
    """Scan a standalone Node.js project (not in pnpm workspace)."""
    entries: list[ExplorerEntryCreate] = []

    try:
        deps = _parse_package_json(package_json)

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

            entries.append(
                ExplorerEntryCreate(
                    path=f"nodejs/{name}",
                    name=name,
                    health_status="unknown",
                    metadata=metadata,
                )
            )

    except Exception as e:
        logger.warning(f"Failed to scan standalone Node project: {e}")

    return entries


def _run_pnpm_audit(workspace_root: Path) -> dict[str, dict[str, Any]]:
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
                            "vulnerabilities": {
                                "critical": 0,
                                "high": 0,
                                "medium": 0,
                                "low": 0,
                            },
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


def _run_pnpm_outdated(workspace_root: Path) -> dict[str, dict[str, Any]]:
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
