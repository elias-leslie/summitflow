"""CLI-only bridge for checked-main publication. No backend, DB or worker is required.

Aico owns selection, scheduling and Status. This leaf retains the existing authenticated
Git transport, outgoing-history verifier and workflow-effects guard. Never handles tokens.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Local publication source is unavailable")
    return result.stdout.strip()


def _path(root: Path, sha: str) -> Path:
    return Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "aico-checks" / "receipts" / f"publish-{sha}.json"


def record_local_check(root: Path, sha: str, *, passed: bool, lane: str = "quick",
                       failed: list[str] | None = None) -> None:
    """Record only a check the caller actually ran on this immutable source."""
    import re

    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        raise ValueError("Local check requires a full commit OID")
    value = {"kind": "aico.local-check.v1", "sha": sha,
             "tree": _git(root, "rev-parse", f"{sha}^{{tree}}"), "passed": passed,
             "lane": lane, "failed": failed or [], "at": datetime.now(UTC).isoformat()}
    path = _path(root, sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value))
    os.replace(temporary, path)


def checked_main(root: Path, sha: str) -> bool:
    """Recheck the job's proof at the transport boundary; never accept a private unchecked commit."""
    import re

    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
        return False

    try:
        if _git(root, "rev-parse", "refs/heads/main") != sha:
            return False
        value = json.loads(_path(root, sha).read_text())
        return (isinstance(value, dict) and value.get("kind") == "aico.local-check.v1"
                and value.get("sha") == sha and value.get("tree") == _git(root, "rev-parse", f"{sha}^{{tree}}")
                and value.get("passed") is True and value.get("failed") == [])
    except (OSError, ValueError):
        return False


def failed_check_names(detail: str) -> list[str]:
    """Keep only check protocol names, never diagnostic text, in publication Status."""
    import re

    ids = re.findall(r"CHECK:FAIL:([A-Za-z0-9_.-]+)", detail)
    tags = re.findall(r"\b([A-Z][A-Z0-9_-]*):FAIL:", detail)
    ids.extend({"TEST": "pytest", "LINT": "ruff", "TYPES": "types"}.get(tag, tag.lower())
               for tag in tags if tag != "CHECK")
    return sorted(set(ids)) or ["acceptance"]


def deliver(root: Path, sha: str, *, authorized_workflows: tuple[str, ...] = ()) -> dict[str, Any]:
    from app.tasks.backup_publish import _public_evidence, publish_source

    if not checked_main(root, sha):
        return {"publication_complete": False, "pushed": False, "reason": "local_check_required"}
    # No registry/service lookup here. Aico resolved the registered root and policy before this call.
    source = {"id": root.name, "project_id": root.name, "path": str(root),
              "source_type": "project", "enabled": True}
    return _public_evidence(publish_source(source, sha, authorized_workflows=authorized_workflows,
                                         checked_main=True))
