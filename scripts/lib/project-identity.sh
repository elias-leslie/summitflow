#!/usr/bin/env bash

PROJECT_IDENTITY_FILE_NAME="${PROJECT_IDENTITY_FILE_NAME:-project.identity.json}"

project_identity_manifest_from_root() {
    local root="$1"
    [ -n "$root" ] || return 1
    [ -d "$root" ] || return 1

    local manifest="$root/$PROJECT_IDENTITY_FILE_NAME"
    [ -f "$manifest" ] || return 1
    printf '%s\n' "$manifest"
}

project_identity_ids_from_workspace() {
    local workspace_projects_root="${1:-${PROJECT_ROOTS_WORKSPACES_ROOT:-/srv/workspaces}/projects}"
    [ -d "$workspace_projects_root" ] || return 0

    find "$workspace_projects_root" -maxdepth 2 -name "$PROJECT_IDENTITY_FILE_NAME" -print0 2>/dev/null |
        python3 -c '
import json
import sys
from pathlib import Path

ids = []
for raw_path in sys.stdin.buffer.read().split(b"\0"):
    if not raw_path:
        continue
    path = Path(raw_path.decode())
    try:
        payload = json.loads(path.read_text())
    except Exception:
        continue
    project = payload.get("project")
    if not isinstance(project, dict):
        continue
    project_id = project.get("id")
    if isinstance(project_id, str) and project_id:
        ids.append(project_id)

for project_id in sorted(dict.fromkeys(ids)):
    print(project_id)
'
}

project_identity_manifest_for_project() {
    local project="$1"
    local workspace_projects_root="${2:-${PROJECT_ROOTS_WORKSPACES_ROOT:-/srv/workspaces}/projects}"
    [ -n "$project" ] || return 1
    [ -d "$workspace_projects_root" ] || return 1

    local direct_manifest="$workspace_projects_root/$project/$PROJECT_IDENTITY_FILE_NAME"
    if [ -f "$direct_manifest" ]; then
        printf '%s\n' "$direct_manifest"
        return 0
    fi

    find "$workspace_projects_root" -maxdepth 2 -name "$PROJECT_IDENTITY_FILE_NAME" -print0 2>/dev/null |
        python3 - "$project" <<'PY'
import json
import sys
from pathlib import Path

target = sys.argv[1]

for raw_path in sorted(sys.stdin.buffer.read().split(b"\0")):
    if not raw_path:
        continue
    path = Path(raw_path.decode())
    try:
        payload = json.loads(path.read_text())
    except Exception:
        continue
    project = payload.get("project")
    if not isinstance(project, dict):
        continue

    aliases = set()
    for key in ("id", "repo_name"):
        value = project.get(key)
        if isinstance(value, str) and value:
            aliases.add(value)
    for key in ("legacy_ids", "repo_aliases"):
        values = project.get(key)
        if isinstance(values, list):
            aliases.update(value for value in values if isinstance(value, str) and value)

    if target in aliases:
        print(path)
        break
PY
}

project_identity_load_env_from_manifest() {
    local manifest="$1"
    [ -f "$manifest" ] || return 1

    python3 - "$manifest" <<'PY'
import json
import shlex
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
project = payload.get("project", {})
branding = payload.get("branding", {})
runtime = payload.get("runtime", {})
services = payload.get("services", {})
hosts = payload.get("hosts", {})
artifacts = payload.get("artifacts", {})


def _flatten(value):
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


env = {
    "PROJECT_IDENTITY_ID": project.get("id", ""),
    "PROJECT_IDENTITY_REPO_NAME": project.get("repo_name", ""),
    "PROJECT_IDENTITY_DISPLAY_NAME": project.get("display_name", ""),
    "PROJECT_IDENTITY_LEGACY_IDS": project.get("legacy_ids", []),
    "PROJECT_IDENTITY_REPO_ALIASES": project.get("repo_aliases", []),
    "PROJECT_IDENTITY_SHORT_NAME": branding.get("short_name", ""),
    "PROJECT_IDENTITY_DESCRIPTION": branding.get("description", ""),
    "PROJECT_IDENTITY_BACKEND_PORT": runtime.get("backend_port", 0),
    "PROJECT_IDENTITY_FRONTEND_PORT": runtime.get("frontend_port", 0),
    "PROJECT_IDENTITY_BACKEND_DIR": runtime.get("backend_dir", "."),
    "PROJECT_IDENTITY_FRONTEND_DIR": runtime.get("frontend_dir", "."),
    "PROJECT_IDENTITY_HEALTH_ENDPOINT": runtime.get("health_endpoint", "/health"),
    "PROJECT_IDENTITY_BACKEND_SERVICE": services.get("backend", ""),
    "PROJECT_IDENTITY_FRONTEND_SERVICE": services.get("frontend", ""),
    "PROJECT_IDENTITY_DEFAULT_WORKERS": services.get("default_workers", []),
    "PROJECT_IDENTITY_OPTIONAL_WORKERS": services.get("optional_workers", []),
    "PROJECT_IDENTITY_PRODUCTION_FRONTEND": hosts.get("production_frontend", ""),
    "PROJECT_IDENTITY_PRODUCTION_API": hosts.get("production_api", ""),
    "PROJECT_IDENTITY_PYTHON_DISTRIBUTION": artifacts.get("python_distribution", ""),
    "PROJECT_IDENTITY_PYTHON_MODULE": artifacts.get("python_module", ""),
    "PROJECT_IDENTITY_CACHE_DIR_NAME": artifacts.get("cache_dir_name", ""),
    "PROJECT_IDENTITY_UPLOAD_DIR_NAME": artifacts.get("upload_dir_name", ""),
}

for key, value in env.items():
    print(f"{key}={shlex.quote(_flatten(value))}")
PY
}
