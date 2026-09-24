"""Ingest the browser owner's versioned runtime inventory into Explorer."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ....utils import safe_subprocess
from ..models import ExplorerEntryCreate

_RUNTIME_ID = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_OWNER_PROJECT = "browser-automation"
_STATUS = {"observed": "checked", "unchecked": "unknown", "absent": "absent", "error": "failed"}


def scan_browser_runtime_dependencies(project_id: str, root_path: Path) -> list[ExplorerEntryCreate]:
    """Read browser runtimes through the public ST owner route, never owner internals."""
    if project_id != _OWNER_PROJECT:
        return []
    st_bin = shutil.which("st")
    if not st_bin:
        raise ValueError("ST browser runtime inventory route is unavailable")
    try:
        result = safe_subprocess.run(
            [st_bin, "browser", "inventory", "--json"], cwd=root_path,
            capture_output=True, text=True, check=False, timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Browser owner runtime inventory failed") from exc
    if result.returncode != 0:
        raise ValueError("Browser owner runtime inventory failed")
    try:
        payload: Any = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError("Browser owner runtime inventory was not JSON") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("owner") != _OWNER_PROJECT
        or payload.get("scope") != "local-host"
        or not isinstance(payload.get("runtimes"), list)
        or not payload["runtimes"]
    ):
        raise ValueError("Browser owner runtime inventory contract mismatch")
    entries: list[ExplorerEntryCreate] = []
    seen: set[str] = set()
    for runtime in payload["runtimes"]:
        if not isinstance(runtime, dict):
            raise ValueError("Browser owner runtime inventory entry is invalid")
        name = runtime.get("id")
        if not isinstance(name, str) or not _RUNTIME_ID.fullmatch(name) or name in seen:
            raise ValueError("Browser owner runtime inventory id is invalid")
        seen.add(name)
        installed_status = runtime.get("installed_status")
        if installed_status not in {"observed", "absent", "error"}:
            raise ValueError("Browser owner runtime installed status is invalid")
        installed_version = runtime.get("installed_version")
        if installed_version is not None and not isinstance(installed_version, str):
            raise ValueError("Browser owner runtime installed version is invalid")
        if installed_status != "observed" and installed_version is not None:
            raise ValueError("Browser owner runtime version conflicts with status")
        executable = runtime.get("executable")
        if executable is not None and not isinstance(executable, str):
            raise ValueError("Browser owner runtime executable is invalid")
        for field in ("latest", "recommended"):
            status = runtime.get(f"{field}_status")
            version = runtime.get(f"{field}_version")
            if status not in _STATUS or (version is not None and not isinstance(version, str)):
                raise ValueError(f"Browser owner runtime {field} evidence is invalid")
            if status != "observed" and version is not None:
                raise ValueError(f"Browser owner runtime {field} version conflicts with status")
        entries.append(ExplorerEntryCreate(
            path=f"browser-runtime/{name}", name=name,
            metadata={
                "package_type": "browser-runtime",
                "constraint": None,
                "locked_version": None,
                "installed_version": installed_version,
                "installed_check_status": _STATUS[installed_status],
                "latest_version": runtime.get("latest_version"),
                "latest_check_status": _STATUS[runtime["latest_status"]],
                "recommended_version": runtime.get("recommended_version"),
                "recommended_check_status": _STATUS[runtime["recommended_status"]],
                "relationship": "direct", "is_dev_dependency": False,
                "environment": "local-host", "source_file": executable,
                "audit_check_status": "unknown",
            },
        ))
    return entries
