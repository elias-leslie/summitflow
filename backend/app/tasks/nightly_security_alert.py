"""Nightly security alert: one Nightshift summary push per night for fixable runtime-dependency advisories.

Each night the committed lockfiles (uv.lock, pnpm-lock.yaml, package-lock.json) of every active project go through
the same osv-scanner invocation ``st check security`` uses, under heavy-work admission. A finding counts only when the
package is a runtime dependency and the advisory names a fixed version above the locked one. After every project is
scanned, at most one push goes to Nightshift's PWA Web Push (``nightshift push``) and nowhere else: how many fixable
advisories in how many projects, then one line per project. Nothing is sent on a clean night. An advisory that stays
unfixed shows up in the next night's summary again; that is the point, so nothing is remembered between nights.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..logging_config import get_logger
from .backup_canaries import _nightshift
from .nightly_publication import _projects

logger = get_logger(__name__)

LOCK_NAMES = ("uv.lock", "pnpm-lock.yaml", "package-lock.json")
SUMMARY_QUIET_SECONDS = 20 * 3600  # a hand re-run the same night stays quiet; the key carries the date
SUMMARY_PACKAGES_SHOWN = 2  # packages named per project line before "+N more"
SUMMARY_MAX_CHARS = 3900  # Nightshift keeps 4000 characters for the detail page; the lock screen shows the first 180
SCAN_TIMEOUT_SECONDS = 600
PUSH_TIMEOUT_SECONDS = 60


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version.split("+")[0]))


def _normal(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def committed_lockfiles(root: Path) -> list[str]:
    """Lockfiles tracked in git at HEAD, so a dirty worktree never changes the answer."""
    from .backup_publish import _git

    listed = _git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD")
    if listed.returncode != 0:
        return []
    return sorted(path for path in listed.stdout.split("\0") if path and Path(path).name in LOCK_NAMES)


def _materialize(root: Path, paths: list[str], destination: Path) -> list[Path]:
    from .backup_publish import _git

    written = []
    for path in paths:
        shown = _git(root, "show", f"HEAD:{path}")
        if shown.returncode != 0:
            continue
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shown.stdout)
        written.append(target)
    return written


def _uv_runtime(lock: Path) -> set[str] | None:
    """Package names reachable from the project roots through ``dependencies`` (not dev groups or extras)."""
    packages = tomllib.loads(lock.read_text()).get("package", [])
    by_name = {_normal(package["name"]): package for package in packages}
    pending = [_normal(package["name"]) for package in packages
               if {"virtual", "editable", "directory"} & set(package.get("source", {}))]
    seen: set[str] = set()
    while pending:
        name = pending.pop()
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        pending.extend(_normal(dependency["name"]) for dependency in by_name[name].get("dependencies", []))
    return seen or None


def _pnpm_runtime(lock: Path) -> set[str] | None:
    """``name@version`` keys reachable from every importer's dependencies (devDependencies excluded)."""
    data = yaml.safe_load(lock.read_text()) or {}
    snapshots = data.get("snapshots")
    if snapshots is None:
        return None
    pending = []
    for importer in (data.get("importers") or {".": data}).values():
        for section in ("dependencies", "optionalDependencies"):
            for name, spec in (importer.get(section) or {}).items():
                version = spec.get("version") if isinstance(spec, dict) else spec
                if version and not str(version).startswith(("link:", "file:", "workspace:")):
                    pending.append(f"{name}@{version}")
    seen: set[str] = set()
    while pending:
        key = pending.pop()
        if key in seen or key not in snapshots:
            continue
        seen.add(key)
        entry = snapshots[key] or {}
        for section in ("dependencies", "optionalDependencies"):
            pending.extend(f"{name}@{version}" for name, version in (entry.get(section) or {}).items())
    return {re.sub(r"\(.*", "", key) for key in seen}  # drop peer-suffixes so keys match osv's name@version


def runtime_packages(lock: Path) -> set[str] | None:
    """Runtime package identifiers for lockfiles OSV cannot classify; None means classification was unavailable."""
    try:
        if lock.name == "uv.lock":
            return _uv_runtime(lock)
        if lock.name == "pnpm-lock.yaml":
            return _pnpm_runtime(lock)
    except Exception:
        logger.warning("security_alert_runtime_unreadable", lockfile=lock.name)
    return None


def _fixed_version(vulnerability: dict[str, Any], name: str, current: str) -> str | None:
    """Lowest fixed version above ``current`` in a range that covers ``current``."""
    best: tuple[tuple[int, ...], str] | None = None
    here = _version_key(current)
    for affected in vulnerability.get("affected", []):
        if _normal(affected.get("package", {}).get("name", "")) != _normal(name):
            continue
        for range_ in affected.get("ranges", []):
            if range_.get("type") not in {"SEMVER", "ECOSYSTEM"}:
                continue
            introduced = "0"
            for event in range_.get("events", []):
                introduced = event.get("introduced", introduced)
                fixed = event.get("fixed")
                if fixed and _version_key(introduced) <= here < _version_key(fixed):
                    candidate = (_version_key(fixed), fixed)
                    best = candidate if best is None else min(best, candidate)
    return best[1] if best else None


def findings_from_osv(data: dict[str, Any], base: Path) -> list[dict[str, str]]:
    """Fixable runtime findings in one osv-scanner JSON document, one per package + advisory."""
    findings: dict[tuple[str, str], dict[str, str]] = {}
    for result in data.get("results", []):
        lock = Path(result.get("source", {}).get("path", ""))
        runtime = None if lock.name == "package-lock.json" else runtime_packages(lock)
        for entry in result.get("packages", []):
            package = entry["package"]
            name, version = package["name"], package["version"]
            if lock.name == "package-lock.json":
                if entry.get("dependency_groups"):
                    continue
            elif runtime is not None:
                key = _normal(name) if lock.name == "uv.lock" else f"{name}@{version}"
                if key not in runtime:
                    continue
            vulnerabilities = {item["id"]: item for item in entry.get("vulnerabilities", [])}
            for group in entry.get("groups", []):
                ids = sorted(group.get("ids", []))
                fixes = [fix for advisory in ids
                         if (fix := _fixed_version(vulnerabilities.get(advisory, {}), name, version))]
                if not fixes:
                    continue
                fixed = min(fixes, key=_version_key)
                findings.setdefault((name, ids[0]), {
                    "package": name, "version": version, "fixed": fixed, "advisory": ids[0],
                    "lockfile": str(lock.relative_to(base)) if lock.is_relative_to(base) else lock.name,
                })
    return [findings[key] for key in sorted(findings)]


def scan_project(root: Path) -> list[dict[str, str]] | None:
    """Fixable runtime findings for a project's committed lockfiles; None when it could not be scanned."""
    from cli.commands.check_security import osv_command
    from cli.lib.ci_parity import canonical_tool_path

    from ..utils import safe_subprocess
    from ..utils.heavy_work import HeavyWorkError, heavy_work

    paths = committed_lockfiles(root)
    if not paths:
        return []
    with tempfile.TemporaryDirectory(prefix="st-security-alert-") as temporary:
        base = Path(temporary)
        lockfiles = _materialize(root, paths, base)
        if not lockfiles:
            return None
        try:
            with heavy_work("nightly security alert", work_class="heavy") as work:
                result = safe_subprocess.run_inherited(
                    work.command(osv_command(lockfiles)), inherit_fds=work.pass_fds,
                    env=work.environment({**os.environ, "PATH": canonical_tool_path()}),
                    timeout=SCAN_TIMEOUT_SECONDS,
                )
        except (OSError, subprocess.SubprocessError, HeavyWorkError):
            return None
        try:
            data = json.loads(result.stdout)
        except ValueError:
            data = None
        if result.returncode not in {0, 1} or not isinstance(data, dict):
            return None  # osv exits 1 when it found advisories; anything else is a failed scan
        return findings_from_osv(data, base)


def summarize(by_project: dict[str, list[dict[str, str]]]) -> tuple[str, str] | None:
    """(title, message) for one night's fixable findings per project; None when there are none."""
    by_project = {project: items for project, items in by_project.items() if items}
    if not by_project:
        return None
    total = sum(len(items) for items in by_project.values())
    count = len(by_project)
    lines = [f"{total} fixable security {'advisory' if total == 1 else 'advisories'} in "
             f"{count} {'project' if count == 1 else 'projects'}."]
    for project, items in sorted(by_project.items()):
        packages: dict[str, dict[str, str]] = {}
        for item in items:
            packages.setdefault(item["package"], item)
        shown = [f"{item['package']} {item['version']} -> {item['fixed']}"
                 for item in list(packages.values())[:SUMMARY_PACKAGES_SHOWN]]
        more = len(packages) - len(shown)
        noun = "package" if len(packages) == 1 else "packages"
        lines.append(f"{project}: {len(packages)} {noun}, {', '.join(shown)}{f', +{more} more' if more else ''}")
    while len("\n".join(lines)) > SUMMARY_MAX_CHARS and len(lines) > 2:
        lines.pop()
        lines[-1] = f"{lines[-1]}\n+ more projects"
    return "Security fixes available", "\n".join(lines)


def push_summary(title: str, message: str, *, night: str, quiet_seconds: int = SUMMARY_QUIET_SECONDS) -> bool:
    """Send the one Nightshift Web Push; True when Nightshift accepted it."""
    binary = _nightshift()
    if binary is None:
        return False
    try:
        result = subprocess.run(
            [binary, "push", "--title", title, "--severity", "warning",
             "--key", f"dependency-advisory-summary:{night}", "--cooldown", str(quiet_seconds), message],
            capture_output=True, text=True, timeout=PUSH_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def run_nightly_security_alert(*, project_ids: list[str] | None = None, send: bool = True) -> dict[str, Any]:
    """Scan each active project, then push one summary of the fixable findings; ``send=False`` only builds it."""
    rows: list[dict[str, Any]] = []
    found: dict[str, list[dict[str, str]]] = {}
    for project_id, root in _projects(project_ids):
        try:
            findings = scan_project(root)
        except Exception:
            logger.warning("nightly_security_alert_scan_failed", project_id=project_id)
            findings = None
        if findings is None:
            rows.append({"project_id": project_id, "state": "scan_failed"})
            continue
        found[project_id] = findings
        rows.append({"project_id": project_id, "state": "scanned", "fixable_runtime": len(findings)})
    summary = summarize(found)
    sent = False
    if summary and send:
        sent = push_summary(*summary, night=datetime.now(UTC).date().isoformat())
    return {"status": "completed", "alerts_sent": int(sent), "projects": rows,
            **({"summary": summary[1]} if summary else {})}
