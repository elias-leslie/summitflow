"""Python dependency scanning for Explorer.

Handles parsing of pyproject.toml, uv.lock files, and running pip-audit
and pip outdated checks.
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


def scan_python_dependencies(
    project_id: str,
    root_path: Path,
) -> list[ExplorerEntryCreate]:
    """Scan Python dependencies from pyproject.toml and uv.lock.

    Args:
        project_id: Project identifier for path generation
        root_path: Root path to search for Python dependency files

    Returns:
        List of explorer entries for Python dependencies
    """
    entries: list[ExplorerEntryCreate] = []

    # Find pyproject.toml files
    pyproject_files = list(root_path.rglob("pyproject.toml"))
    # Filter out reference/vendor directories
    pyproject_files = [
        p
        for p in pyproject_files
        if "references" not in str(p) and "node_modules" not in str(p) and ".venv" not in str(p)
    ]

    # Run pip-audit once for the project if available
    audit_results = _run_python_audit(root_path)
    outdated_results = _run_python_outdated(root_path)

    for pyproject_path in pyproject_files:
        try:
            deps = _parse_pyproject_toml(pyproject_path)
            lock_versions = _parse_uv_lock(pyproject_path.parent / "uv.lock")

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
                    "vulnerabilities": vuln_info.get(
                        "vulnerabilities", {"critical": 0, "high": 0, "medium": 0, "low": 0}
                    ),
                    "audit_advisories": vuln_info.get("advisories", []),
                    "source_file": str(pyproject_path),
                }

                # Determine health
                health = calculate_health_for_entry("dependency", metadata)

                # Path format: python/{source_dir}/{package_name}
                rel_source = pyproject_path.parent.relative_to(root_path)
                path = f"python/{rel_source}/{name}"

                entries.append(
                    ExplorerEntryCreate(
                        path=path,
                        name=name,
                        health_status=health,
                        metadata=metadata,
                    )
                )

        except Exception as e:
            logger.warning(f"Failed to parse {pyproject_path}: {e}")

    return entries


def _parse_pyproject_toml(path: Path) -> dict[str, dict[str, Any]]:
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
                    r'["\']?([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?([<>=!~^][^"\']*)?["\']?', stripped
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


def _parse_uv_lock(path: Path) -> dict[str, str]:
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


def _run_python_audit(root_path: Path) -> dict[str, dict[str, Any]]:
    """Run pip-audit and return vulnerability info by package."""
    results: dict[str, dict[str, Any]] = {}

    try:
        # Try pip-audit first
        venv_path = root_path / ".venv" / "bin" / "pip-audit"
        if venv_path.exists():
            cmd = [str(venv_path), "--format", "json"]
        else:
            # Fall back to system pip-audit
            cmd = ["pip-audit", "--format", "json"]

        proc = subprocess.run(
            cmd,
            cwd=root_path,
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


def _run_python_outdated(root_path: Path) -> dict[str, dict[str, Any]]:
    """Check for outdated Python packages."""
    results: dict[str, dict[str, Any]] = {}

    try:
        venv_pip = root_path / ".venv" / "bin" / "pip"
        if venv_pip.exists():
            cmd = [str(venv_pip), "list", "--outdated", "--format", "json"]
        else:
            cmd = ["pip", "list", "--outdated", "--format", "json"]

        proc = subprocess.run(
            cmd,
            cwd=root_path,
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
