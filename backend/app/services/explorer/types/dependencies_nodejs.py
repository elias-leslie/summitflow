"""Node.js dependency scanning for Explorer."""

from __future__ import annotations

import fnmatch
import json
import subprocess
from collections import deque
from pathlib import Path
from typing import TypedDict

import yaml

from ....logging_config import get_logger
from ....project_identity import get_project_identity
from ....utils import safe_subprocess
from ..constants import FORBIDDEN_DIRS, SKIP_DIRS
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)

MONOREPO_ROOT = Path.home()
_EMPTY_VULNS: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
_LOCKFILES = ["pnpm-lock.yaml", "package-lock.json", "yarn.lock", "bun.lockb"]
_NODE_SKIP_DIRS = SKIP_DIRS | FORBIDDEN_DIRS | {"source-lab", "source_lab", ".pnpm-store"}
_MAX_WORKSPACE_DEPTH = 8
_MAX_WORKSPACE_DIRECTORIES = 256


class _AuditEntry(TypedDict):
    vulnerabilities: dict[str, int]
    advisories: list[str]


def scan_nodejs_dependencies(
    project_id: str, root_path: Path, *, include_network_checks: bool = True,
) -> list[ExplorerEntryCreate]:
    """Scan root, declared workspaces, and immediate child apps.

    Local inventory can omit online enrichment; existing callers retain it.
    Descendant discovery never walks arbitrary source trees. Declared workspace
    patterns are restricted to eight levels and 256 directory visits.
    """
    root_path = root_path.resolve()
    workspace_root = _find_pnpm_workspace_root(root_path)
    if not workspace_root:
        logger.debug("No pnpm workspace found, scanning %s as standalone", project_id)
        return _scan_local_node_projects(project_id, root_path, include_network_checks)
    workspace_packages = _parse_pnpm_workspace(workspace_root)
    if workspace_packages is None:
        return _scan_local_node_projects(project_id, root_path, include_network_checks)
    root_package = workspace_root / "package.json"
    if root_path == workspace_root and root_package.exists():
        workspace_packages = sorted({root_package, *workspace_packages})
    is_in_workspace = _is_project_in_workspace(root_path, workspace_packages)
    has_own_lockfile = _has_own_lockfile(root_path)
    if not is_in_workspace or (has_own_lockfile and root_path != workspace_root):
        logger.info(
            "Project %s has own resolution context "
            "(in_workspace=%s, own_lockfile=%s), "
            "scanning as standalone",
            project_id, is_in_workspace, has_own_lockfile,
        )
        return _scan_local_node_projects(project_id, root_path, include_network_checks)
    logger.debug("Scanning %s as part of pnpm workspace at %s", project_id, workspace_root)
    lock_versions = _parse_pnpm_lock(workspace_root / "pnpm-lock.yaml")
    audit_result = _run_pnpm_audit(workspace_root) if include_network_checks else ({}, "unknown")
    audit_results, audit_status = audit_result if isinstance(audit_result, tuple) else (audit_result, "unknown")
    outdated_results = _run_pnpm_outdated(workspace_root) if include_network_checks else {}
    entries: list[ExplorerEntryCreate] = []
    for pkg_path in sorted(set(p for p in workspace_packages if p.is_relative_to(root_path))):
        try:
            rel = pkg_path.parent.relative_to(root_path)
            for name, info in _parse_package_json(pkg_path).items():
                constraint = str(info.get("version", ""))
                od, vi = outdated_results.get(name, {}), audit_results.get(name, _AuditEntry(vulnerabilities=dict(_EMPTY_VULNS), advisories=[]))
                meta = {"package_type": "nodejs", "constraint": constraint, "locked_version": lock_versions.get(name), "installed_version": _installed_node_version(pkg_path.parent, name), "latest_version": od.get("latest"), "is_outdated": od.get("outdated", False), "is_workspace_ref": "workspace:" in constraint, "is_dev_dependency": info.get("dev", False), "relationship": "direct", "audit_check_status": audit_status, "vulnerabilities": vi["vulnerabilities"], "audit_advisories": vi["advisories"], "source_file": str(pkg_path)}
                entries.append(ExplorerEntryCreate(path=f"nodejs/{rel}/{name}", name=name, health_status=calculate_health_for_entry("dependency", meta), metadata=meta))
        except (KeyError, TypeError, ValueError, OSError) as e:
            logger.warning("Failed to parse %s: %s", pkg_path, e)
    if root_path == workspace_root:
        direct_names = {entry.name for entry in entries}
        for name, locked_version in lock_versions.items():
            if name in direct_names:
                continue
            vi = audit_results.get(name, _AuditEntry(vulnerabilities=dict(_EMPTY_VULNS), advisories=[]))
            meta = {"package_type": "nodejs", "constraint": None, "locked_version": locked_version, "installed_version": None, "latest_version": None, "relationship": "transitive", "is_dev_dependency": False, "audit_check_status": audit_status, "vulnerabilities": vi["vulnerabilities"], "audit_advisories": vi["advisories"], "source_file": str(workspace_root / "pnpm-lock.yaml")}
            entries.append(ExplorerEntryCreate(path=f"nodejs/transitive/{name}", name=name, health_status="unknown", metadata=meta))
    return sorted(entries, key=lambda entry: entry.path)


def _safe_node_directory(root_path: Path, candidate: Path) -> bool:
    """Reject ignored paths and symlink escapes before reading descendants."""
    try:
        relative = candidate.relative_to(root_path)
        if _NODE_SKIP_DIRS.intersection(relative.parts) or any(
            part.startswith(".") for part in relative.parts
        ):
            return False
        resolved_relative = candidate.resolve().relative_to(root_path.resolve())
        return not _NODE_SKIP_DIRS.intersection(resolved_relative.parts) and not any(
            part.startswith(".") for part in resolved_relative.parts
        )
    except (OSError, ValueError):
        return False


def _node_child_directories(root_path: Path, directory: Path) -> list[Path]:
    try:
        return sorted(
            child for child in directory.iterdir()
            if _safe_node_directory(root_path, child) and child.is_dir()
        )[:_MAX_WORKSPACE_DIRECTORIES]
    except OSError as exc:
        logger.warning("Failed to inspect Node app directories at %s: %s", directory, exc)
        return []


def _workspace_manifests(workspace_root: Path, patterns: list[str]) -> list[Path]:
    """Expand only declared paths, with shared exclusions and a fixed visit budget."""
    packages: set[Path] = set()
    visits = 0
    exclusions = [pattern[1:].removeprefix("./") for pattern in patterns if pattern.startswith("!")]
    for pattern in sorted(set(patterns)):
        if pattern.startswith("!"):
            continue
        path = Path(pattern)
        if path.is_absolute() or ".." in path.parts or len(path.parts) > _MAX_WORKSPACE_DEPTH:
            continue
        pending = deque([(workspace_root, 0)])
        seen: set[tuple[Path, int]] = set()
        while pending and visits < _MAX_WORKSPACE_DIRECTORIES:
            directory, index = pending.popleft()
            if (directory, index) in seen or not _safe_node_directory(workspace_root, directory):
                continue
            seen.add((directory, index))
            visits += 1
            if index == len(path.parts):
                manifest = directory / "package.json"
                if _safe_node_directory(workspace_root, manifest) and manifest.is_file():
                    packages.add(manifest.resolve())
                continue
            part = path.parts[index]
            if part == "**":
                pending.append((directory, index + 1))
            if len(directory.relative_to(workspace_root).parts) >= _MAX_WORKSPACE_DEPTH:
                continue
            if any(char in part for char in "*?["):
                pending.extend(
                    (child, index if part == "**" else index + 1)
                    for child in _node_child_directories(workspace_root, directory)
                    if part == "**" or fnmatch.fnmatchcase(child.name, part)
                )
            else:
                pending.append((directory / part, index + 1))
        if pending:
            logger.warning("Node workspace discovery limit reached at %s", workspace_root)
            break
    return sorted(
        manifest for manifest in packages
        if not any(fnmatch.fnmatchcase(
            manifest.parent.relative_to(workspace_root.resolve()).as_posix(), pattern,
        ) for pattern in exclusions)
    )


def _package_workspace_manifests(root_path: Path) -> list[Path]:
    try:
        payload = json.loads((root_path / "package.json").read_text())
        workspaces = payload.get("workspaces", []) if isinstance(payload, dict) else []
        patterns = workspaces.get("packages", []) if isinstance(workspaces, dict) else workspaces
        return _workspace_manifests(root_path, [p for p in patterns if isinstance(p, str)]) if isinstance(patterns, list) else []
    except (OSError, ValueError) as exc:
        logger.debug("No readable package workspaces at %s: %s", root_path, exc)
        return []


def _scan_local_node_projects(
    project_id: str, root_path: Path, include_network_checks: bool,
) -> list[ExplorerEntryCreate]:
    directories = {root_path, *_node_child_directories(root_path, root_path)}
    if (root_path / "project.identity.json").is_file():
        try:
            identity = get_project_identity(project_id, str(root_path)) or {}
            frontend_dir = identity.get("runtime", {}).get("frontend_dir")
            if isinstance(frontend_dir, str):
                candidate = root_path / frontend_dir
                if _safe_node_directory(root_path, candidate):
                    directories.add(candidate)
        except (OSError, ValueError, AttributeError) as exc:
            logger.warning("Failed to read project app directory for %s: %s", project_id, exc)
    manifests: set[Path] = set()
    for directory in sorted(directories):
        manifest = directory / "package.json"
        if _safe_node_directory(root_path, manifest) and manifest.exists():
            manifests.add(manifest.resolve())
        if (directory / "pnpm-workspace.yaml").is_file():
            manifests.update(_parse_pnpm_workspace(directory) or [])
        if manifest.is_file():
            manifests.update(_package_workspace_manifests(directory))
    entries: list[ExplorerEntryCreate] = []
    for manifest in sorted(manifests):
        for entry in _scan_standalone_node_project(manifest, include_network_checks=include_network_checks):
            relative = manifest.parent.relative_to(root_path.resolve())
            if relative != Path("."):
                entry.path = f"nodejs/{relative}/{entry.path.removeprefix('nodejs/')}"
            entries.append(entry)
    return sorted(entries, key=lambda entry: entry.path)


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
    return any(p.is_relative_to(root_path) for p in workspace_packages)


def _has_own_lockfile(root_path: Path) -> bool:
    return any((root_path / lf).exists() for lf in _LOCKFILES)


def _parse_pnpm_workspace(workspace_root: Path) -> list[Path] | None:
    try:
        payload = yaml.safe_load((workspace_root / "pnpm-workspace.yaml").read_text())
        patterns = payload.get("packages", []) if isinstance(payload, dict) else []
        return _workspace_manifests(workspace_root, [p for p in patterns if isinstance(p, str)]) if isinstance(patterns, list) else []
    except (OSError, ValueError, yaml.YAMLError) as e:
        logger.warning("Failed to parse pnpm-workspace.yaml: %s", e)
    return None


def _parse_pnpm_lock(path: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    if not path.exists():
        return versions
    try:
        payload = yaml.safe_load(path.read_text()) or {}
        for key in (payload.get("packages") or {}):
            if "@" not in key:
                continue
            name, version = str(key).rsplit("@", 1)
            version = version.split("(", 1)[0]
            if name and version and not version.startswith("http"):
                versions[name] = version
    except (OSError, yaml.YAMLError, TypeError) as exc:
        logger.warning("Failed to parse pnpm-lock.yaml: %s", exc)
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
    except (json.JSONDecodeError, OSError, KeyError, TypeError) as e:
        logger.warning("Failed to parse package.json %s: %s", path, e)
    return deps


def _scan_standalone_node_project(
    package_json: Path, *, include_network_checks: bool = True,
) -> list[ExplorerEntryCreate]:
    entries: list[ExplorerEntryCreate] = []
    try:
        root = package_json.parent
        lock_versions = _parse_pnpm_lock(root / "pnpm-lock.yaml")
        audit_result = _run_pnpm_audit(root) if include_network_checks and (root / "pnpm-lock.yaml").exists() else ({}, "unknown")
        audit, audit_status = audit_result if isinstance(audit_result, tuple) else (audit_result, "unknown")
        outdated = _run_pnpm_outdated(root) if include_network_checks and (root / "pnpm-lock.yaml").exists() else {}
        for name, info in _parse_package_json(package_json).items():
            vi = audit.get(name, _AuditEntry(vulnerabilities=dict(_EMPTY_VULNS), advisories=[]))
            meta = {"package_type": "nodejs", "constraint": info.get("version", ""), "locked_version": lock_versions.get(name), "installed_version": _installed_node_version(root, name), "latest_version": outdated.get(name, {}).get("latest"), "is_outdated": outdated.get(name, {}).get("outdated", False), "is_workspace_ref": False, "is_dev_dependency": info.get("dev", False), "relationship": "direct", "audit_check_status": audit_status, "vulnerabilities": vi["vulnerabilities"], "audit_advisories": vi["advisories"], "source_file": str(package_json)}
            entries.append(ExplorerEntryCreate(path=f"nodejs/{name}", name=name, health_status="unknown", metadata=meta))
        direct_names = {entry.name for entry in entries}
        for name, locked_version in lock_versions.items():
            if name not in direct_names:
                entries.append(ExplorerEntryCreate(path=f"nodejs/transitive/{name}", name=name, health_status="unknown", metadata={"package_type": "nodejs", "constraint": None, "locked_version": locked_version, "installed_version": _installed_node_version(root, name), "latest_version": None, "relationship": "transitive", "audit_check_status": audit_status, "source_file": str(root / "pnpm-lock.yaml")}))
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("Failed to scan standalone Node project: %s", e)
    return entries


def _run_pnpm_audit(workspace_root: Path) -> tuple[dict[str, _AuditEntry], str]:
    results: dict[str, _AuditEntry] = {}
    try:
        proc = safe_subprocess.run(["pnpm", "audit", "--json"], cwd=workspace_root, capture_output=True, text=True, timeout=120)
        if not proc.stdout:
            return results, "failed"
        try:
            payload = json.loads(proc.stdout)
            for _id, adv in payload.get("advisories", {}).items():
                pkg = adv.get("module_name", "")
                if pkg not in results:
                    results[pkg] = _AuditEntry(vulnerabilities=dict(_EMPTY_VULNS), advisories=[])
                severity = adv.get("severity", "unknown").lower()
                if severity in results[pkg]["vulnerabilities"]:
                    results[pkg]["vulnerabilities"][severity] += 1
                cves = adv.get("cves") or ["Unknown"]
                results[pkg]["advisories"].append(f"{cves[0]}: {adv.get('title', '')[:100]}")
            return results, "checked" if "advisories" in payload else "unknown"
        except json.JSONDecodeError:
            pass
    except FileNotFoundError:
        logger.info("pnpm not available, skipping Node.js security scan")
    except subprocess.TimeoutExpired:
        logger.warning("pnpm audit timed out")
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("pnpm audit failed: %s", e)
    return results, "unknown"


def _installed_node_version(package_root: Path, name: str) -> str | None:
    """Read the installed package version, separately from the lockfile."""
    try:
        package_file = package_root / "node_modules" / name / "package.json"
        return str(json.loads(package_file.read_text())["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _run_pnpm_outdated(workspace_root: Path) -> dict[str, dict[str, str | bool | None]]:
    results: dict[str, dict[str, str | bool | None]] = {}
    try:
        proc = safe_subprocess.run(["pnpm", "outdated", "--json"], cwd=workspace_root, capture_output=True, text=True, timeout=60)
        if proc.stdout:
            try:
                for pkg, info in json.loads(proc.stdout).items():
                    results[pkg] = {"latest": info.get("latest"), "current": info.get("current"), "wanted": info.get("wanted"), "outdated": True}
            except json.JSONDecodeError:
                pass
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        logger.warning("pnpm outdated check failed: %s", e)
    return results
