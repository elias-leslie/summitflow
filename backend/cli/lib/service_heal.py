"""Keep a project's units on its current release.

``restart_onto_current`` restarts units onto the release ``current`` already
points at, with no build (so it never waits in heavy-work admission).
``heal_project`` finds units a user would see broken and restarts them that
way: a unit whose process runs from a removed release, a unit the current
deploy's scope covered that still runs an older release, and a page that
answers 404 (or fails) while ``/health`` answers 200. Manual workers (Tether)
are never restarted here; a problem with one is reported for an owner alert.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import httpx

from . import service_ops, service_release

RESTART_LOG = "restarts.jsonl"


@dataclass(frozen=True)
class Problem:
    unit: str
    kind: str  # release_missing | not_current | page_down
    detail: str
    restartable: bool


def _releases(project_id: str) -> Path:
    return service_release.project_state_dir(project_id) / "releases"


def _release_pattern(releases: Path) -> re.Pattern[str]:
    return re.compile(re.escape(str(releases.resolve()) + "/") + r"([0-9a-f]{32})(?![0-9a-f])")


def unit_release(unit: str, releases: Path) -> tuple[str, bool] | None:
    """(build id, removed?) of the release a unit's main process runs from, else None."""
    pid = service_ops._service_main_pid(unit)
    if not pid:
        return None
    try:
        cwd = os.readlink(service_ops._PROC_ROOT / str(pid) / "cwd")
    except OSError:
        return None
    match = _release_pattern(releases).match(cwd)
    if match is None:
        return None
    build = match.group(1)
    return build, cwd.endswith(" (deleted)") or not (releases / build).is_dir()


def _unit_file_builds(unit: str, releases: Path) -> set[str]:
    """Release ids a unit's file and drop-ins name (rendered by the last deploy of that unit)."""
    paths = [service_ops._systemctl_value(unit, "FragmentPath"),
             *service_ops._systemctl_value(unit, "DropInPaths").split()]
    pattern = _release_pattern(releases)
    builds: set[str] = set()
    for path in filter(None, paths):
        try:
            builds.update(pattern.findall(Path(path).read_text()))
        except OSError:
            continue
    return builds


def _deployment_scope(receipt: dict[str, Any] | None) -> tuple[str, tuple[str, ...]]:
    for event in (receipt or {}).get("events", ()):
        if isinstance(event, dict) and event.get("phase") == "deployment_scope":
            workers = event.get("workers")
            return str(event.get("scope") or ""), tuple(w for w in workers or () if isinstance(w, str))
    return "", ()


def expected_on_current(project: service_ops.ProjectServices, receipt: dict[str, Any] | None) -> set[str]:
    """Units the current release's deploy restarted (or should have), so they belong on it."""
    scope, workers = _deployment_scope(receipt)
    expected: set[str] = set()
    if scope in {"full", "backend", "worker"} and project.backend_service:
        expected.add(project.backend_service)
    if scope in {"full", "frontend"} and project.page_service:
        expected.add(project.page_service)
    expected.update(worker for worker in workers if worker not in project.manual_workers)
    return {service_ops.activated_service(unit) or service_ops.canonical_unit(unit) for unit in expected}


def migrations_cover(project: service_ops.ProjectServices, receipt: dict[str, Any] | None) -> bool:
    """Whether the backend may restart onto current without a migration run first."""
    if not (project.backend_dir / "alembic.ini").exists():
        return True
    return any(isinstance(event, dict) and event.get("phase") == "migrations" and event.get("status") == "succeeded"
               for event in (receipt or {}).get("events", ()))


def _probe(port: int, path: str) -> int | None:
    try:
        return httpx.get(f"http://127.0.0.1:{port}{path}", timeout=3.0).status_code
    except httpx.HTTPError:
        return None


def _page_problem(project: service_ops.ProjectServices) -> Problem | None:
    """The page fails (404, 5xx or no answer) while the backend's health check passes."""
    if not (project.page_service and project.page_port > 0 and project.backend_service and project.backend_port > 0):
        return None
    health = _probe(project.backend_port, project.health_endpoint)
    if health is None or not 200 <= health < 300:
        return None
    page = _probe(project.page_port, "/")
    if page is not None and page != 404 and page < 500:
        return None
    unit = service_ops.activated_service(project.page_service) or service_ops.canonical_unit(project.page_service)
    return Problem(unit, "page_down", f"/ answers {page or 'nothing'} while {project.health_endpoint} answers {health}",
                   restartable=unit not in project.manual_workers)


def find_problems(project: service_ops.ProjectServices) -> list[Problem]:
    current = service_release.current_build(project.project_id)
    if current is None:
        return []
    releases = _releases(project.project_id)
    receipt = service_release.build_receipt(project.project_id, current)
    expected = expected_on_current(project, receipt)
    manual = {service_ops.canonical_unit(unit) for unit in project.manual_workers}
    backend_ok = migrations_cover(project, receipt)
    backend = service_ops.canonical_unit(project.backend_service)
    problems: list[Problem] = []
    for raw in (*project.all_services, *project.manual_workers):
        unit = service_ops.activated_service(raw) or service_ops.canonical_unit(raw)
        found = unit_release(unit, releases)
        if found is None:
            continue
        build, removed = found
        restartable = unit not in manual and (unit != backend or backend_ok)
        if removed:
            problems.append(Problem(unit, "release_missing", f"runs from removed release {build[:8]}", restartable))
        elif build != current and unit in expected:
            problems.append(Problem(unit, "not_current", f"runs release {build[:8]}; current is {current[:8]}",
                                    restartable))
    if page := _page_problem(project):
        problems.append(replace(page, restartable=page.restartable
                                and (page.unit != backend or backend_ok)))
    return problems


def _port(project: service_ops.ProjectServices, unit: str) -> int:
    if unit == service_ops.canonical_unit(project.backend_service):
        return project.backend_port
    if project.frontend_service and unit == service_ops.canonical_unit(project.frontend_service):
        return project.frontend_port
    return 0


def record(project_id: str, entry: dict[str, Any]) -> None:
    """Append one restart to the project's restart log (service state, next to its receipts)."""
    path = service_release.project_state_dir(project_id) / RESTART_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        log.write(json.dumps({"at": time.time(), "project": project_id, **entry}) + "\n")


def recent_restarts(project_id: str, *, reason: str, since: float) -> list[dict[str, Any]]:
    path = service_release.project_state_dir(project_id) / RESTART_LOG
    try:
        lines = path.read_text().splitlines()[-200:]
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("reason") == reason and float(entry.get("at") or 0) >= since:
            entries.append(entry)
    return entries


def restart_onto_current(project: service_ops.ProjectServices, units: list[str], *, reason: str,
                         problems: Sequence[Problem] = ()) -> int:
    """Restart units onto ``current`` without building; return the error count.

    Each unit's file must already name the current release (the last deploy
    rendered it), so a restart cannot move a unit onto anything else.
    """
    current = service_release.current_build(project.project_id)
    source = service_release.current_source_root(project.project_id)
    if current is None or source is None:
        print(f"[service] {project.project_id} has no current release to restart onto")
        return 1
    releases = _releases(project.project_id)
    bound = service_ops.project_at_source(project, source,
                                          source_sha=service_release.build_commit(project.project_id, current) or "")
    errors = 0
    restarted: list[str] = []
    for unit in dict.fromkeys(units):
        named = _unit_file_builds(unit, releases)
        if named - {current}:
            print(f"[service] {unit} FAIL: its unit file names release {sorted(named)[0][:8]}, not current "
                  f"{current[:8]}; run st service rebuild {project.project_id}")
            errors += 1
            continue
        errors += service_ops.restart_service(unit, port=_port(project, unit), project=bound) != 0
        restarted.append(unit)
    canonical = set(restarted)
    selected = replace(
        bound,
        backend_service=bound.backend_service if service_ops.canonical_unit(bound.backend_service) in canonical else "",
        frontend_service=bound.frontend_service if bound.frontend_service and (
            service_ops.activated_service(bound.frontend_service)
            or service_ops.canonical_unit(bound.frontend_service)) in canonical else "",
    )
    if restarted and (selected.backend_service or selected.frontend_service):
        errors += service_ops.verify_health(selected)
    record(project.project_id, {"reason": reason, "release": current, "units": restarted,
                                "problems": [asdict(problem) for problem in problems],
                                "result": "succeeded" if errors == 0 else "failed"})
    return errors


def heal_project(project_id: str, *, cooldown_seconds: float, dry_run: bool = False) -> dict[str, Any]:
    """Find and fix units users would see broken; the result's status drives any owner alert.

    ``ok``/``healed``/``busy``/``skipped`` need nobody; ``failed`` (the restart
    did not fix it, or it broke again within the cooldown) and
    ``needs_attention`` (a problem this may not restart) go to the owner.
    """
    result: dict[str, Any] = {"project": project_id, "status": "ok", "problems": [], "restarted": []}
    try:
        project = service_ops.load_project(project_id)
    except service_ops.ServiceError as exc:
        return {**result, "status": "skipped", "detail": str(exc)}
    if project.runtime_user or project.deployment:
        return {**result, "status": "skipped", "detail": "runs outside this user's service manager"}
    try:
        with service_release.deployment_lock(project.project_id):
            return _heal_locked(project, result, cooldown_seconds=cooldown_seconds, dry_run=dry_run)
    except service_release.ReleaseError as exc:
        if "already in progress" in str(exc):
            return {**result, "status": "busy", "detail": "a deploy is running"}
        return {**result, "status": "failed", "detail": str(exc)}


def _heal_locked(project: service_ops.ProjectServices, result: dict[str, Any], *, cooldown_seconds: float,
                 dry_run: bool) -> dict[str, Any]:
    problems = find_problems(project)
    result["problems"] = [asdict(problem) for problem in problems]
    if not problems:
        return result
    units = list(dict.fromkeys(problem.unit for problem in problems if problem.restartable))
    blocked = [problem for problem in problems if not problem.restartable]
    recent = {unit for entry in recent_restarts(project.project_id, reason="self-heal",
                                                since=time.time() - cooldown_seconds)
              for unit in entry.get("units") or ()}
    repeat = [unit for unit in units if unit in recent]
    units = [unit for unit in units if unit not in recent]
    if dry_run:
        return {**result, "status": "found", "would_restart": units}
    errors = restart_onto_current(project, units, reason="self-heal", problems=problems) if units else 0
    result["restarted"] = units
    remaining = [problem for problem in find_problems(project) if problem.unit in units] if units else []
    if errors or remaining or repeat:
        detail = []
        if repeat:
            detail.append(f"{', '.join(repeat)} broke again within {int(cooldown_seconds // 60)} min of a restart")
        if errors or remaining:
            detail.append("the restart onto the current release did not fix it")
        return {**result, "status": "failed", "detail": "; ".join(detail)}
    if blocked:
        return {**result, "status": "needs_attention",
                "detail": "; ".join(f"{problem.unit} {problem.detail}" for problem in blocked)}
    return {**result, "status": "healed"}
