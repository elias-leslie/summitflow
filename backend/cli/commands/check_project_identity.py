"""Read-only checkout and registry identity gate for aggregate st check runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ._projects_helpers import get_api_base


def _fetch(path: str) -> Any:
    with httpx.Client(timeout=3.0) as client:
        response = client.get(f"{get_api_base()}{path}")
        response.raise_for_status()
        return response.json()


def run_project_identity_check(root: Path) -> int:
    """Fail proven identity drift; keep network-only evidence unavailable offline."""
    manifest_path = root / "project.identity.json"
    if not manifest_path.is_file():
        print("IDENTITY:SKIP:no_manifest")
        return 0
    try:
        identity = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"IDENTITY:FAIL:invalid_manifest:{exc}")
        return 1
    project = identity.get("project") if isinstance(identity, dict) else None
    if not isinstance(project, dict):
        print("IDENTITY:FAIL:missing_project")
        return 1
    project_id = project.get("id")
    if not isinstance(project_id, str) or not project_id:
        print("IDENTITY:FAIL:missing_project_id")
        return 1
    lifecycle = project.get("lifecycle", "active")
    failures = []
    if not isinstance(lifecycle, str) or lifecycle not in {"active", "retired"}:
        failures.append("invalid_lifecycle")
    if not (root / ".git").exists():
        failures.append("missing_git_checkout")
    if failures:
        print(f"IDENTITY:FAIL:{','.join(failures)}")
        return 1
    remote_unknown = False
    try:
        registered = _fetch(f"/projects/{project_id}")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            failures.append("not_registered")
            registered = None
        else:
            registered = None
            remote_unknown = True
            print("IDENTITY:UNKNOWN:registry_unavailable")
    except (httpx.HTTPError, OSError, ValueError):
        registered = None
        remote_unknown = True
        print("IDENTITY:UNKNOWN:registry_unavailable")
    if isinstance(registered, dict):
        if registered.get("id") != project_id:
            failures.append("registry_id_mismatch")
        registered_root = registered.get("root_path")
        if not isinstance(registered_root, str) or not registered_root:
            failures.append("registry_root_missing")
        elif Path(registered_root).expanduser().resolve() != root.resolve() and not (root / ".git").is_file():
            failures.append("registry_root_mismatch")
        elif Path(registered_root).expanduser().resolve() != root.resolve():
            remote_unknown = True
            print("IDENTITY:UNKNOWN:worktree_registry_root_differs")
        effective_lifecycle = registered.get("lifecycle")
        if not isinstance(effective_lifecycle, str) or effective_lifecycle not in {"active", "retired"}:
            failures.append("registry_lifecycle_missing")
        elif lifecycle in {"active", "retired"} and lifecycle != effective_lifecycle:
            print(
                "IDENTITY:ADVISORY:manifest_lifecycle_differs:"
                f"declared={lifecycle},effective={effective_lifecycle}"
            )
        expected_visible = effective_lifecycle == "active" and registered.get("category") != "testing"
        try:
            default_list = _fetch("/projects")
        except (httpx.HTTPError, OSError, ValueError):
            remote_unknown = True
            print("IDENTITY:UNKNOWN:default_listing_unavailable")
        else:
            if isinstance(default_list, list):
                observed_visible = any(isinstance(row, dict) and row.get("id") == project_id for row in default_list)
                if expected_visible != observed_visible:
                    failures.append("default_listing_mismatch")
            else:
                failures.append("default_listing_invalid")
    elif registered is not None:
        failures.append("registry_response_invalid")
    if failures:
        print(f"IDENTITY:FAIL:{','.join(failures)}")
        return 1
    print(f"IDENTITY:{'PARTIAL' if remote_unknown else 'OK'}:{project_id}")
    return 0
