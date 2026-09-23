"""Import source-bound acceptance, deployment and observed live evidence."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def load_completion_evidence(path: Path, *, project_root: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or set(payload) - {"acceptance_receipt", "deployment_receipt", "live_validation"}:
        raise ValueError("Expected acceptance_receipt, deployment_receipt and/or live_validation evidence")
    receipts: dict[str, Any] = {}
    if acceptance := payload.get("acceptance_receipt"):
        from cli.lib.acceptance import AcceptanceError, validate_acceptance_receipt

        artifact = Path(acceptance)
        if not artifact.is_absolute():
            artifact = path.parent / artifact
        try:
            receipts["acceptance"] = validate_acceptance_receipt(project_root, artifact, sha="HEAD")
        except AcceptanceError as exc:
            raise ValueError(str(exc)) from exc
    if deployment := payload.get("deployment_receipt"):
        from cli.lib.service_release import validate_deployment_receipt

        artifact = Path(deployment)
        if not artifact.is_absolute():
            artifact = path.parent / artifact
        receipts["deployment"] = validate_deployment_receipt(artifact, project_root=project_root)
    if live := payload.get("live_validation"):
        source = str(live.get("source_commit") or "")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source):
            raise ValueError("Live validation requires a full immutable source commit")
        checks = live.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ValueError("Live validation requires observed checks and evidence artifacts")
        validated = []
        seen: set[str] = set()
        for check in checks:
            if not isinstance(check, dict) or not isinstance(check.get("id"), str) or not check["id"].strip():
                raise ValueError("Each live check requires an ID")
            if check["id"] in seen or check.get("state") not in {"success", "failed"}:
                raise ValueError("Live check IDs must be unique and states success or failed")
            seen.add(check["id"])
            artifact = Path(check.get("artifact") or "")
            if not artifact.is_absolute():
                artifact = path.parent / artifact
            artifact = artifact.resolve(strict=True)
            if not artifact.is_file():
                raise ValueError("Live check evidence must be a regular file")
            with artifact.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if check.get("sha256") and check["sha256"] != digest:
                raise ValueError(f"Live evidence digest changed for {check['id']}")
            validated.append({**check, "artifact": str(artifact), "sha256": digest})
        receipts["live_validation"] = {"source_commit": source, "checks": validated}
    if not receipts:
        raise ValueError("No completion evidence supplied")
    return receipts
