"""Node.js dependency scanning for Explorer."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TypedDict

from ....logging_config import get_logger
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

MONOREPO_ROOT = Path("/home/kasadis")
_EMPTY_VULNS: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
_LOCKFILES = ["pnpm-lock.yaml", "package-lock.json", "yarn.lock", "bun.lockb"]


class _AuditEntry(TypedDict):
    vulnerabilities: dict[str, int]
    advisories: list[str]


def scan_nodejs_dependencies(project_id: str, root_path: Path) -> list[ExplorerEntryCreate]:
    """Scan Node.js dependencies using multi-context discovery."""
    workspace_root = _find_pnpm_workspace_root(root_path)
    if not workspace_root:
        logger.debug("No pnpm workspace found, scanning %s as standalone", project_id)
        pkg = root_path / "package.json"
        return _scan_standalone_node_project(pkg) if pkg.exists() else []
    workspace_packages = _parse_pnpm_workspace(workspace_root)
    is_in_workspace = _is_project_in_workspace(root_path, workspace_packages)
    has_own_lockfile = _has_own_lockfile(root_path)
    if not is_in_workspace or has_own_lockfile:
        logger.info(
            "Project %s has own resolution context "
            "(in_workspace=%s, own_lockfile=%s), "
            "scanning as standalone",
            project_id, is_in_workspace, has_own_lockfile,
        )
        pkg = root_path / "package.json"
        return _scan_standalone_node_project(pkg) if pkg.exists() else []
    logger.debug("Scanning %s as part of pnpm workspace at %s", project_id, workspace_root)
    lock_versions = _parse_pnpm_lock(workspace_root / "pnpm-lock.yaml")
    audit_results = _run_pnpm_audit(workspace_root)
    outdated_results = _run_pnpm_outdated(workspace_root)
    entries: list[ExplorerEntryCreate] = []
    for pkg_path in (p for p in workspace_packages if str(p).startswith(str(root_path))):
        try:
            rel = pkg_path.parent.relative_to(root_path)
            for name, info in _parse_package_json(pkg_path).items():
                constraint = str(info.get("version", ""))
                od, vi = outdated_results.get(name, {}), audit_results.get(name, _AuditEntry(vulnerabilities=dict(_EMPTY_VULNS), advisories=[]))
                meta = {"package_type": "nodejs", "constraint": constraint, "locked_version": lock_versions.get(name), "latest_version": od.get("latest"), "is_outdated": od.get("outdated", False), "is_workspace_ref": "workspace:" in constraint, "is_dev_dependency": info.get("dev", False), "vulnerabilities": vi["vulnerabilities"], "audit_advisories": vi["advisories"], "source_file": str(pkg_path)}
                entries.append(ExplorerEntryCreate(path=f"nodejs/{rel}/{name}", name=name, health_status=calculate_health_for_entry("dependency", meta), metadata=meta))
        except Exception as e:
            logger.warning("Failed to parse %s: %s", pkg_path, e)
    return entries


def _find_pnpm_workspace_root(root_path: Path) -> Path | None:
    current = root_path
    for _ in range(5):
        if (current / "pnpm-workspace.yaml").exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return MONOREPO_ROOT if (MONOREPO_ROOT / "pnpm-workspace.yaml").exists() else None


def _is_project_in_workspace(root_path: Path, workspace_packages: list[Path]) -> bool:
    root_str = str(root_path)
    return any(str(p).startswith(root_str) for p in workspace_packages)


def _has_own_lockfile(root_path: Path) -> bool:
    return any((root_path / lf).exists() for lf in _LOCKFILES)


def _parse_pnpm_workspace(workspace_root: Path) -> list[Path]:
    packages: list[Path] = []
    try:
        in_packages = False
        for line in (workspace_root / "pnpm-workspace.yaml").read_text().splitlines():
            stripped = line.strip()
            if stripped == "packages:":
                in_packages = True
                continue
            if not in_packages:
                continue
            if not stripped.startswith("-"):
                if not stripped.startswith("#") and stripped:
                    break
                continue
            pattern = stripped.lstrip("- ").strip("'\"")
            if "*" in pattern:
                base, glob_part = pattern.rsplit("/", 1)
                base_path = workspace_root / base
                if base_path.exists():
                    packages.extend(m / "package.json" for m in base_path.glob(glob_part) if (m / "package.json").exists())
            else:
                pkg_json = workspace_root / pattern / "package.json"
                if pkg_json.exists():
                    packages.append(pkg_json)
    except Exception as e:
        logger.warning("Failed to parse pnpm-workspace.yaml: %s", e)
    return packages


def _parse_pnpm_lock(path: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    if not path.exists():
        return versions
    try:
        for line in path.read_text().splitlines():
            m = re.match(r"['\"]?/?([^@]+)@([^:'\"]+)", line.strip())
            if m:
                name, version = m.group(1), m.group(2)
                if "/" not in name and not version.startswith("http"):
                    versions[name] = version
    except Exception as e:
        logger.warning("Failed to parse pnpm-lock.yaml: %s", e)
    return versions


def _parse_package_json(path: Path) -> dict[str, dict[str, str | bool]]:
    deps: dict[str, dict[str, str | bool]] = {}
    try:
        content = json.loads(path.read_text())
        for name, version in content.get("dependencies", {}).items():
            deps[name] = {"version": version, "dev": False}
        for name, version in content.get("devDependencies", {}).items():
            deps[name] = {"version": version, "dev": True}
        for name, version in content.get("peerDependencies", {}).items():
            if name not in deps:
                deps[name] = {"version": version, "dev": False, "peer": True}
    except Exception as e:
        logger.warning("Failed to parse package.json %s: %s", path, e)
    return deps


def _scan_standalone_node_project(package_json: Path) -> list[ExplorerEntryCreate]:
    entries: list[ExplorerEntryCreate] = []
    try:
        for name, info in _parse_package_json(package_json).items():
            meta = {"package_type": "nodejs", "constraint": info.get("version", ""), "locked_version": None, "latest_version": None, "is_outdated": False, "is_workspace_ref": False, "is_dev_dependency": info.get("dev", False), "vulnerabilities": dict(_EMPTY_VULNS), "audit_advisories": [], "source_file": str(package_json)}
            entries.append(ExplorerEntryCreate(path=f"nodejs/{name}", name=name, health_status="unknown", metadata=meta))
    except Exception as e:
        logger.warning("Failed to scan standalone Node project: %s", e)
    return entries


def _run_pnpm_audit(workspace_root: Path) -> dict[str, _AuditEntry]:
    results: dict[str, _AuditEntry] = {}
    try:
        proc = subprocess.run(["pnpm", "audit", "--json"], cwd=workspace_root, capture_output=True, text=True, timeout=120)
        if not proc.stdout:
            return results
        try:
            for _id, adv in json.loads(proc.stdout).get("advisories", {}).items():
                pkg = adv.get("module_name", "")
                if pkg not in results:
                    results[pkg] = _AuditEntry(vulnerabilities=dict(_EMPTY_VULNS), advisories=[])
                severity = adv.get("severity", "unknown").lower()
                if severity in results[pkg]["vulnerabilities"]:
                    results[pkg]["vulnerabilities"][severity] += 1
                cves = adv.get("cves") or ["Unknown"]
                results[pkg]["advisories"].append(f"{cves[0]}: {adv.get('title', '')[:100]}")
        except json.JSONDecodeError:
            pass
    except FileNotFoundError:
        logger.info("pnpm not available, skipping Node.js security scan")
    except subprocess.TimeoutExpired:
        logger.warning("pnpm audit timed out")
    except Exception as e:
        logger.warning("pnpm audit failed: %s", e)
    return results


def _run_pnpm_outdated(workspace_root: Path) -> dict[str, dict[str, str | bool | None]]:
    results: dict[str, dict[str, str | bool | None]] = {}
    try:
        proc = subprocess.run(["pnpm", "outdated", "--json"], cwd=workspace_root, capture_output=True, text=True, timeout=60)
        if proc.stdout:
            try:
                for pkg, info in json.loads(proc.stdout).items():
                    results[pkg] = {"latest": info.get("latest"), "current": info.get("current"), "wanted": info.get("wanted"), "outdated": True}
            except json.JSONDecodeError:
                pass
    except Exception as e:
        logger.warning("pnpm outdated check failed: %s", e)
    return results
