"""Python dependency scanning for Explorer (pyproject.toml, uv.lock, pip-audit)."""
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
_SKIP_DIRS = {"references", "node_modules", ".venv"}
_EMPTY_VULNS: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}


def scan_python_dependencies(project_id: str, root_path: Path) -> list[ExplorerEntryCreate]:
    """Scan Python dependencies from pyproject.toml and uv.lock."""
    pyproject_files = [p for p in root_path.rglob("pyproject.toml") if not _SKIP_DIRS.intersection(p.parts)]
    audit_results = _run_python_audit(root_path)
    outdated_results = _run_python_outdated(root_path)
    entries: list[ExplorerEntryCreate] = []
    for pp in pyproject_files:
        try:
            deps = _parse_pyproject_toml(pp)
            locks = _parse_uv_lock(pp.parent / "uv.lock")
            rel = pp.parent.relative_to(root_path)
            for name, constraint in deps.items():
                entries.append(_build_dep_entry(name, constraint, locks, audit_results, outdated_results, rel, pp))
        except Exception as e:
            logger.warning(f"Failed to parse {pp}: {e}")
    return entries


def _build_dep_entry(
    name: str, constraint: dict[str, Any], locks: dict[str, str],
    audit: dict[str, dict[str, Any]], outdated: dict[str, dict[str, Any]],
    rel: Path, src: Path,
) -> ExplorerEntryCreate:
    """Build an ExplorerEntryCreate for one Python dependency."""
    ver = constraint.get("version", "")
    oi, vi = outdated.get(name, {}), audit.get(name, {})
    meta = {
        "package_type": "python", "constraint": ver,
        "locked_version": locks.get(name), "latest_version": oi.get("latest"),
        "is_outdated": oi.get("outdated", False), "is_workspace_ref": "file://" in ver,
        "is_dev_dependency": constraint.get("dev", False),
        "vulnerabilities": vi.get("vulnerabilities", dict(_EMPTY_VULNS)),
        "audit_advisories": vi.get("advisories", []), "source_file": str(src),
    }
    return ExplorerEntryCreate(
        path=f"python/{rel}/{name}", name=name,
        health_status=calculate_health_for_entry("dependency", meta), metadata=meta,
    )


_DEP_RE = re.compile(r'["\']?([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?([<>=!~^][^"\']*)?["\']?')


def _parse_pyproject_toml(path: Path) -> dict[str, dict[str, Any]]:
    """Parse pyproject.toml dependencies (name -> {version, dev})."""
    try:
        content = path.read_text()
    except Exception as e:
        logger.warning(f"Failed to parse pyproject.toml {path}: {e}")
        return {}
    deps: dict[str, dict[str, Any]] = {}
    in_deps, section = False, ""
    for line in content.splitlines():
        s = line.strip()
        if s.startswith("["):
            in_deps = "dependencies" in s
            section = "dev" if "dev" in s.lower() else "main"
        elif s.startswith("dependencies = ["):
            in_deps, section = True, "main"
        elif in_deps and s.startswith("]"):
            in_deps = False
        elif in_deps:
            m = _DEP_RE.match(s)
            if m:
                deps[m.group(1).lower().replace("_", "-")] = {"version": (m.group(2) or "").strip(), "dev": section == "dev"}
    return deps


def _parse_uv_lock(path: Path) -> dict[str, str]:
    """Parse uv.lock for exact locked versions (name -> version)."""
    if not path.exists():
        return {}
    versions: dict[str, str] = {}
    try:
        cur = None
        for line in path.read_text().splitlines():
            s = line.strip()
            if s.startswith('name = "'):
                cur = s.split('"')[1].lower().replace("_", "-")
            elif s.startswith('version = "') and cur:
                versions[cur] = s.split('"')[1]
                cur = None
    except Exception as e:
        logger.warning(f"Failed to parse uv.lock {path}: {e}")
    return versions


def _venv_cmd(root_path: Path, tool: str) -> list[str]:
    """Return venv tool command, falling back to system PATH."""
    p = root_path / ".venv" / "bin" / tool
    return [str(p)] if p.exists() else [tool]


def _run_python_audit(root_path: Path) -> dict[str, dict[str, Any]]:
    """Run pip-audit and return vulnerability info by package."""
    results: dict[str, dict[str, Any]] = {}
    try:
        proc = subprocess.run([*_venv_cmd(root_path, "pip-audit"), "--format", "json"],
                              cwd=root_path, capture_output=True, text=True, timeout=120)
        if not proc.stdout:
            return results
        for vuln in json.loads(proc.stdout).get("vulnerabilities", []):
            pkg = vuln.get("name", "").lower().replace("_", "-")
            e = results.setdefault(pkg, {"vulnerabilities": dict(_EMPTY_VULNS), "advisories": []})
            sev = vuln.get("severity", "unknown").lower()
            if sev in e["vulnerabilities"]:
                e["vulnerabilities"][sev] += 1
            e["advisories"].append(f"{vuln.get('id', 'Unknown')}: {vuln.get('description', '')[:100]}")
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
        proc = subprocess.run([*_venv_cmd(root_path, "pip"), "list", "--outdated", "--format", "json"],
                              cwd=root_path, capture_output=True, text=True, timeout=60)
        if not proc.stdout:
            return results
        for pkg in json.loads(proc.stdout):
            n = pkg.get("name", "").lower().replace("_", "-")
            results[n] = {"latest": pkg.get("latest_version"), "current": pkg.get("version"), "outdated": True}
    except Exception as e:
        logger.warning(f"pip outdated check failed: {e}")
    return results
