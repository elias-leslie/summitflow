"""Read-only project representation audit for the ST CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import typer

from ..output import output_error, output_json
from ._projects_helpers import get_api_base


def _get_list(path: str, *, required: bool = False) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Read a public list API, preserving unavailable evidence as unknown."""
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(f"{get_api_base()}{path}")
            response.raise_for_status()
            value = response.json()
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValueError("expected a JSON list of objects")
        return value, None
    except (httpx.HTTPError, ValueError) as exc:
        if required:
            output_error(f"Cannot audit projects: {path}: {exc}")
            raise typer.Exit(1) from None
        return None, str(exc)


def _checkout(project: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    root = project.get("root_path")
    project_id = project.get("id")
    projects_dir = Path(os.environ["ST_WORKSPACES_ROOT"]) / "projects" if os.getenv("ST_WORKSPACES_ROOT") else Path(__file__).resolve().parents[3].parent
    candidate = projects_dir / str(project.get("id", ""))
    candidate_manifest = candidate / "project.identity.json"
    canonical = None
    candidate_identity = None
    try:
        if candidate_manifest.is_file():
            candidate_payload = json.loads(candidate_manifest.read_text())
            candidate_project = candidate_payload.get("project") if isinstance(candidate_payload, dict) else None
            if isinstance(candidate_project, dict) and candidate_project.get("id") == project_id:
                candidate_identity = candidate_payload
                canonical = str(candidate.resolve())
    except (OSError, ValueError, AttributeError):
        pass
    location = {
        "manifest_checkout": canonical,
        "registry_matches_manifest_checkout": (Path(root).resolve() == Path(canonical)) if root and canonical else None,
    }
    if not isinstance(root, str) or not root:
        return {"path": root, "exists": None, "git": None, "manifest": None, **location}, candidate_identity
    path = Path(root)
    try:
        exists = path.is_dir()
        git = (path / ".git").exists() if exists else False
        manifest_path = path / "project.identity.json"
        manifest_present = manifest_path.is_file() if exists else False
        payload = json.loads(manifest_path.read_text()) if manifest_present else None
        manifest_project = payload.get("project") if isinstance(payload, dict) else None
        manifest_project_id = manifest_project.get("id") if isinstance(manifest_project, dict) else None
        manifest_matches_project = manifest_project_id == project_id if manifest_present else None
        identity = payload if manifest_matches_project else None
        return {
            "path": root,
            "exists": exists,
            "git": git,
            "manifest": manifest_present,
            "manifest_project_id": manifest_project_id,
            "manifest_matches_project": manifest_matches_project,
            "identity_source": "registry_root" if identity is not None else "manifest_checkout" if candidate_identity is not None else None,
            "resolved_path": str(path.resolve()) if exists else None,
            **location,
        }, identity if identity is not None else candidate_identity
    except (OSError, json.JSONDecodeError) as exc:
        return {"path": root, "exists": None, "git": None, "manifest": None, "error": str(exc), **location}, candidate_identity


def _backup(project: dict[str, Any], sources: list[dict[str, Any]] | None) -> dict[str, Any]:
    expected_enabled = False if project.get("category") == "testing" else None
    if sources is None:
        return {"status": "unknown", "expected_enabled": expected_enabled, "sources": []}
    project_id = project["id"]
    matches = [source for source in sources if source.get("project_id") == project_id]
    if not matches:
        return {"status": "not_configured" if expected_enabled is False else "missing", "expected_enabled": expected_enabled, "sources": []}
    root = project.get("root_path")
    result = []
    for source in matches:
        source_path = source.get("path")
        result.append({
            "id": source.get("id"),
            "source_type": source.get("source_type"),
            "path": source_path,
            "enabled": source.get("enabled"),
            "path_matches_checkout": (source_path == root) if root else None,
        })
    mismatch = any(item["path_matches_checkout"] is False for item in result)
    disabled = any(item["enabled"] is False for item in result)
    return {"status": "path_mismatch" if mismatch else "disabled" if disabled else "present", "expected_enabled": expected_enabled, "sources": result}


def _runtime(identity: dict[str, Any] | None, statuses: list[dict[str, Any]] | None) -> dict[str, Any]:
    if identity is None:
        return {"declaration": "unknown", "services": []}
    declarations = identity.get("services")
    if not isinstance(declarations, dict):
        return {"declaration": "none", "services": []}
    units: list[str] = []
    for key in ("backend", "frontend"):
        unit = declarations.get(key)
        if isinstance(unit, str) and unit:
            units.append(unit)
    for key in ("default_workers", "optional_workers"):
        workers = declarations.get(key)
        if isinstance(workers, list):
            units.extend(unit for unit in workers if isinstance(unit, str) and unit)
    seen = set()
    services = []
    for unit in units:
        if unit in seen:
            continue
        seen.add(unit)
        match = next((row for row in statuses or [] if row.get("service") == unit.removesuffix(".service") or row.get("name") == unit), None)
        services.append({
            "unit": unit,
            "observation": "unknown" if statuses is None else "listed" if match else "not_listed",
            "state": match.get("state") if match else None,
            "health": match.get("health") if match else None,
        })
    return {"declaration": "services" if services else "none", "services": services}


def run_audit(project_id: str | None = None) -> None:
    """Read all registered projects, including retired and testing entries."""
    projects, _ = _get_list("/projects?include_inactive=true", required=True)
    assert projects is not None
    if project_id is not None:
        projects = [project for project in projects if project.get("id") == project_id]
        if not projects:
            output_error(f"Project '{project_id}' is not registered")
            raise typer.Exit(1)
    defaults, default_error = _get_list("/projects")
    sources, backup_error = _get_list("/backup-sources")
    statuses, runtime_error = _get_list("/docker/status")
    default_ids = {row.get("id") for row in defaults or []}
    records = []
    for project in projects:
        checkout, identity = _checkout(project)
        lifecycle = project.get("lifecycle")
        category = project.get("category")
        declared_lifecycle = (
            identity.get("project", {}).get("lifecycle", "active")
            if isinstance(identity, dict) and isinstance(identity.get("project"), dict)
            else None
        )
        expected_visible = lifecycle == "active" and category != "testing" if lifecycle and category else None
        records.append({
            "id": project.get("id"),
            "name": project.get("name"),
            "lifecycle": lifecycle,
            "declared_lifecycle": declared_lifecycle,
            "lifecycle_conflict": (
                declared_lifecycle != lifecycle if declared_lifecycle is not None and lifecycle is not None else None
            ),
            "category": category,
            "checkout": checkout,
            "visibility": {
                "expected_default_listing_and_picker": expected_visible,
                "observed_default_listing": project.get("id") in default_ids if defaults is not None else None,
                "observed_picker": None,
            },
            "backup": _backup(project, sources),
            "runtime": _runtime(identity, statuses),
        })
    output_json({
        "projects": records,
        "evidence_errors": {
            "default_listing": default_error,
            "backups": backup_error,
            "runtime": runtime_error,
        },
    })
