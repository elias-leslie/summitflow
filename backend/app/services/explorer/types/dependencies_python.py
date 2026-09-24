"""Python dependency scanning for Explorer (pyproject.toml, uv.lock, pip-audit)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from ....logging_config import get_logger
from ....utils import safe_subprocess
from ..health import calculate_health_for_entry
from ..models import ExplorerEntryCreate

logger = get_logger(__name__)
_SKIP_DIRS = {"references", "node_modules", ".venv"}
_EMPTY_VULNS: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}


def scan_python_dependencies(project_id: str, root_path: Path) -> list[ExplorerEntryCreate]:
    """Scan Python dependencies from pyproject.toml and uv.lock."""
    pyproject_files = [p for p in root_path.rglob("pyproject.toml") if not _SKIP_DIRS.intersection(p.parts)]
    environment_evidence: dict[Path, tuple[dict[str, dict[str, Any]], str, dict[str, dict[str, Any]], dict[str, str]]] = {}
    entries: list[ExplorerEntryCreate] = []
    for pp in pyproject_files:
        try:
            # A monorepo can keep each Python environment beside its manifest.
            env_root = pp.parent if (pp.parent / ".venv" / "bin" / "python").exists() else root_path
            if env_root not in environment_evidence:
                audit_result = _run_python_audit(env_root)
                audit_results, audit_status = audit_result if isinstance(audit_result, tuple) else (audit_result, "unknown")
                environment_evidence[env_root] = (
                    audit_results, audit_status, _run_python_outdated(env_root), _run_python_installed(env_root),
                )
            audit_results, audit_status, outdated_results, installed_results = environment_evidence[env_root]
            deps = _parse_pyproject_toml(pp)
            locks = _parse_uv_lock(pp.parent / "uv.lock")
            rel = pp.parent.relative_to(root_path)
            for name, constraint in deps.items():
                entries.append(_build_dep_entry(name, constraint, locks, audit_results, outdated_results, rel, pp, audit_status, installed_results))
            for name, locked_version in locks.items():
                if name not in deps:
                    meta = {
                        "package_type": "python", "constraint": None, "locked_version": locked_version,
                        "latest_version": None, "installed_version": installed_results.get(name), "relationship": "transitive",
                        "is_dev_dependency": False, "source_file": str(pp.parent / "uv.lock"),
                        "vulnerabilities": audit_results.get(name, {}).get("vulnerabilities", dict(_EMPTY_VULNS)),
                        "audit_advisories": audit_results.get(name, {}).get("advisories", []),
                        "audit_check_status": audit_status,
                    }
                    entries.append(ExplorerEntryCreate(path=f"python/{rel}/transitive/{name}", name=name, health_status="unknown", metadata=meta))
        except (KeyError, TypeError, ValueError, OSError) as e:
            logger.warning("Failed to parse %s: %s", pp, e)
    return entries


def _build_dep_entry(
    name: str, constraint: dict[str, Any], locks: dict[str, str],
    audit: dict[str, dict[str, Any]], outdated: dict[str, dict[str, Any]],
    rel: Path, src: Path, audit_status: str = "unknown",
    installed: dict[str, str] | None = None,
) -> ExplorerEntryCreate:
    """Build an ExplorerEntryCreate for one Python dependency."""
    ver = constraint.get("version", "")
    oi, vi = outdated.get(name, {}), audit.get(name, {})
    meta = {
        "package_type": "python", "constraint": ver,
        "locked_version": locks.get(name), "latest_version": oi.get("latest"),
        "is_outdated": oi.get("outdated", False), "is_workspace_ref": "file://" in ver,
        "is_dev_dependency": constraint.get("dev", False),
        "relationship": "direct", "installed_version": (installed or {}).get(name),
        "audit_check_status": audit_status,
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
        content = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning("Failed to parse pyproject.toml %s: %s", path, e)
        return {}
    deps: dict[str, dict[str, Any]] = {}
    groups = [
        (content.get("project", {}).get("dependencies", []), False),
        *[(items, True) for items in content.get("project", {}).get("optional-dependencies", {}).values()],
        *[(items, True) for items in content.get("dependency-groups", {}).values()],
    ]
    for items, dev in groups:
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, str):
                continue
            m = _DEP_RE.match(item)
            if m:
                name = m.group(1).lower().replace("_", "-")
                deps[name] = {"version": (m.group(2) or "").strip(), "dev": dev}
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
    except (OSError, ValueError) as e:
        logger.warning("Failed to parse uv.lock %s: %s", path, e)
    return versions


def _venv_cmd(root_path: Path, tool: str) -> list[str]:
    """Use only the project's venv; host packages are not project evidence."""
    p = root_path / ".venv" / "bin" / tool
    if not p.exists():
        raise FileNotFoundError(p)
    return [str(p)]


def _package_list_cmd(root_path: Path, *, outdated: bool = False) -> list[str]:
    """Read the selected venv through pip or uv without using host packages."""
    venv = root_path / ".venv" / "bin"
    pip = venv / "pip"
    if pip.exists():
        return [str(pip), "list", *(["--outdated"] if outdated else []), "--format", "json"]
    python = venv / "python"
    uv = shutil.which("uv")
    if python.exists() and uv:
        return [uv, "pip", "list", "--python", str(python), *(["--outdated"] if outdated else []), "--format", "json", "--no-python-downloads"]
    raise FileNotFoundError(f"No pip or uv package listing for {venv}")


def _run_python_audit(root_path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    """Run pip-audit and return vulnerability info by package."""
    results: dict[str, dict[str, Any]] = {}
    try:
        proc = safe_subprocess.run([*_venv_cmd(root_path, "pip-audit"), "--format", "json"],
                              cwd=root_path, capture_output=True, text=True, timeout=120)
        if not proc.stdout:
            return results, "failed"
        payload = json.loads(proc.stdout)
        vulnerabilities = payload.get("vulnerabilities", [])
        for dep in payload.get("dependencies", []):
            for vuln in dep.get("vulns", []):
                vulnerabilities.append({**vuln, "name": dep.get("name")})
        for vuln in vulnerabilities:
            pkg = vuln.get("name", "").lower().replace("_", "-")
            e = results.setdefault(pkg, {"vulnerabilities": dict(_EMPTY_VULNS), "advisories": []})
            sev = vuln.get("severity", "unknown").lower()
            if sev in e["vulnerabilities"]:
                e["vulnerabilities"][sev] += 1
            e["advisories"].append(f"{vuln.get('id', 'Unknown')}: {vuln.get('description', '')[:100]}")
        return results, "checked"
    except FileNotFoundError:
        logger.info("pip-audit not available, skipping Python security scan")
    except subprocess.TimeoutExpired:
        logger.warning("pip-audit timed out")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        logger.warning("pip-audit failed: %s", e)
    return results, "unknown"


def _run_python_outdated(root_path: Path) -> dict[str, dict[str, Any]]:
    """Check for outdated Python packages."""
    results: dict[str, dict[str, Any]] = {}
    try:
        proc = safe_subprocess.run(_package_list_cmd(root_path, outdated=True),
                              cwd=root_path, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return results
        if not proc.stdout:
            return results
        for pkg in json.loads(proc.stdout):
            n = pkg.get("name", "").lower().replace("_", "-")
            results[n] = {"latest": pkg.get("latest_version"), "current": pkg.get("version"), "outdated": True}
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as e:
        logger.warning("pip outdated check failed: %s", e)
    return results


def _run_python_installed(root_path: Path) -> dict[str, str]:
    """Read versions in the project venv without treating lock entries as installed."""
    try:
        proc = safe_subprocess.run(
            _package_list_cmd(root_path),
            cwd=root_path, capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return {}
        return {
            str(item["name"]).lower().replace("_", "-"): str(item["version"])
            for item in json.loads(proc.stdout)
            if isinstance(item, dict) and item.get("name") and item.get("version")
        }
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        return {}
