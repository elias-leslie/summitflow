"""Evidence packets for dependency decisions, backed by Explorer inventory."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..storage import dependency_reviews, explorer_entries
from ..storage.projects import get_project_root_path
from ..utils import safe_subprocess

REVIEW_INTERVAL = timedelta(days=7)
_DEPENDENCY_MANIFESTS = {"pyproject.toml", "uv.lock", "package.json", "pnpm-lock.yaml", "package-lock.json", "yarn.lock", "bun.lockb"}
_SCAN_SKIP_DIRS = {".git", ".venv", "node_modules", "references"}


def _inventory_entry(entry: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    meta = entry.get("metadata") or {}
    checks = {
        "declared": "checked" if meta.get("relationship", "direct") == "direct" and meta.get("constraint") is not None else "unknown",
        "locked": "checked" if meta.get("locked_version") else "unknown",
        "installed": meta.get("installed_check_status") or ("checked" if meta.get("installed_version") else "unknown"),
        "latest": meta.get("latest_check_status") or ("checked" if meta.get("latest_version") else "unknown"),
        "recommended": meta.get("recommended_check_status") or ("checked" if review and review.get("recommended_version") else "unknown"),
        "advisories": meta.get("audit_check_status", "unknown"),
    }
    return {
        "project_id": entry["project_id"],
        "entry_path": entry["path"],
        "name": entry["name"],
        "ecosystem": meta.get("package_type", "unknown"),
        "kind": (
            "dev" if meta.get("is_dev_dependency")
            else "unknown" if meta.get("relationship") == "transitive"
            else "runtime"
        ),
        "relationship": meta.get("relationship", "direct"),
        "owner": entry["project_id"],
        "environment": meta.get("environment", "project"),
        "source_file": meta.get("source_file"),
        "declared_version": meta.get("constraint"),
        "locked_version": meta.get("locked_version"),
        "installed_version": meta.get("installed_version"),
        "latest_version": meta.get("latest_version"),
        "recommended_version": (review.get("recommended_version") if review and review.get("recommended_version") else meta.get("recommended_version")),
        "advisories": meta.get("audit_advisories") or [],
        "vulnerabilities": meta.get("vulnerabilities") if checks["advisories"] == "checked" else None,
        "checks": checks,
        "last_scanned_at": entry.get("last_scanned_at"),
        "review": review,
    }


def list_inventory(
    project_id: str, *, ecosystem: str | None = None,
    status: str | None = None, query: str | None = None,
    limit: int = 100, offset: int = 0,
) -> dict[str, Any]:
    """Read the existing Explorer dataset with the latest decision revision."""
    entries = explorer_entries.get_entries(project_id, {"type": "dependency", "limit": 10000})
    reviews = dependency_reviews.latest_for_project(project_id)
    last_checked = dependency_reviews.checks_for_project(project_id)
    items = [_inventory_entry(entry, reviews.get(entry["path"])) for entry in entries]
    for item in items:
        item["last_review_checked_at"] = last_checked.get(item["entry_path"])
    if ecosystem:
        items = [item for item in items if item["ecosystem"] == ecosystem]
    if status:
        items = [item for item in items if (item["review"] or {}).get("decision", "unreviewed") == status]
    if query:
        lowered = query.casefold()
        items = [item for item in items if lowered in item["name"].casefold()]
    items.sort(key=lambda item: (item["ecosystem"], item["name"], item["entry_path"]))
    return {"project_id": project_id, "total": len(items), "items": items[offset:offset + limit]}


def _github_repository(project_id: str) -> str | None:
    root = get_project_root_path(project_id)
    if not root:
        return None
    result = safe_subprocess.run(
        ["git", "config", "--get", "remote.origin.url"], cwd=root,
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    remote = result.stdout.strip()
    if remote.startswith("git@github.com:"):
        path = remote.removeprefix("git@github.com:")
    else:
        parsed = urlsplit(remote)
        if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password:
            return None
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        return path
    return None


def _hosted_pulls(project_id: str) -> tuple[list[dict[str, Any]], str]:
    repo = _github_repository(project_id)
    if not repo:
        return [], "unknown"
    try:
        response = httpx.get(
            f"https://api.github.com/repos/{repo}/pulls",
            params={"state": "open", "per_page": 100},
            headers={"Accept": "application/vnd.github+json"},
            timeout=15,
        )
        response.raise_for_status()
        pulls = response.json()
        if not isinstance(pulls, list):
            return [], "failed"
    except (httpx.HTTPError, ValueError):
        return [], "failed"
    return pulls, "checked"


def _hosted_proposals(
    project_id: str, name: str, source: tuple[list[dict[str, Any]], str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    pulls, status = source if source is not None else _hosted_pulls(project_id)
    if status != "checked":
        return [], status
    package_pattern = re.compile(rf"(?<![\w./-]){re.escape(name)}(?![\w./-])", re.IGNORECASE)
    proposals = []
    for pull in pulls:
        author = (pull.get("user") or {}).get("login", "")
        if author not in {"dependabot[bot]", "renovate[bot]"}:
            continue
        if not package_pattern.search(f"{pull.get('title') or ''}\n{pull.get('body') or ''}"):
            continue
        proposals.append({
            "engine": "dependabot" if author.startswith("dependabot") else "renovate",
            "number": pull.get("number"),
            "title": pull.get("title"),
            "url": pull.get("html_url"),
            "updated_at": pull.get("updated_at"),
        })
    return proposals, status


def _refresh_scan(project_id: str) -> None:
    from .explorer.types.dependencies import DependencyScanner

    root_text = get_project_root_path(project_id)
    root = Path(root_text) if root_text else None
    if root is None or not root.is_dir():
        raise ValueError(f"Dependency project root unavailable: {project_id}")
    entries = DependencyScanner(project_id).scan()
    if entries:
        explorer_entries.upsert_entries(
            project_id, "dependency", [entry.model_dump() for entry in entries],
        )
        explorer_entries.cleanup_stale_entries(
            project_id, "dependency", {entry.path for entry in entries},
        )
        return
    for _directory, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in _SCAN_SKIP_DIRS]
        if _DEPENDENCY_MANIFESTS.intersection(files):
            raise ValueError("Empty dependency scan with manifests present; retained prior inventory")
    explorer_entries.cleanup_stale_entries(project_id, "dependency", set(), confirmed_empty=True)


def _entry_for_path(project_id: str, entry_path: str, *, refresh: bool) -> dict[str, Any]:
    entry = explorer_entries.get_entry(project_id, "dependency", entry_path)
    if entry is None:
        raise ValueError(f"Dependency entry not found: {entry_path}")
    scanned_at = entry.get("last_scanned_at")
    if isinstance(scanned_at, str):
        scanned_at = datetime.fromisoformat(scanned_at.replace("Z", "+00:00"))
    if refresh or scanned_at is None or datetime.now(UTC) - scanned_at > REVIEW_INTERVAL:
        _refresh_scan(project_id)
        entry = explorer_entries.get_entry(project_id, "dependency", entry_path)
        if entry is None:
            raise ValueError(f"Dependency entry disappeared after scan: {entry_path}")
    return entry


def review_dependency(
    project_id: str, entry_path: str, *, refresh: bool = False,
    hosted_source: tuple[list[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Refresh due evidence, then create at most one revision per evidence hash."""
    entry = _entry_for_path(project_id, entry_path, refresh=refresh)
    current = _inventory_entry(entry, None)
    proposals, proposal_status = _hosted_proposals(project_id, current["name"], hosted_source)
    evidence = {
        "inventory": {key: value for key, value in current.items() if key != "review"},
        "hosted_proposals": proposals,
        "proposal_check_status": proposal_status,
        "engines": {
            "dependabot_cli": "available_unrun" if shutil.which("dependabot") else "unavailable",
            "renovate_local": "available_unrun" if shutil.which("renovate") else "unavailable",
        },
    }
    # Scan timestamps are freshness metadata, not changed dependency evidence.
    hash_material = json.loads(json.dumps(evidence, default=str))
    hash_material["inventory"].pop("last_scanned_at", None)
    digest = hashlib.sha256(json.dumps(hash_material, sort_keys=True).encode()).hexdigest()
    record, created = dependency_reviews.append(
        project_id, entry_path, evidence_hash=digest, evidence=evidence,
        skip_same_evidence=True,
    )
    return {"record": record, "new_evidence": created, "packet": evidence}


def review_due_dependencies(project_id: str, *, now: datetime | None = None) -> dict[str, int]:
    """Review direct packages weekly and advisory changes sooner, without installing."""
    now = now or datetime.now(UTC)
    inventory = list_inventory(project_id, limit=10000)["items"]
    due: list[str] = []
    for item in inventory:
        previous = item["review"]
        prior_advisories = (
            previous.get("evidence", {}).get("inventory", {}).get("advisories", [])
            if previous else []
        )
        new_advisory = bool(item["advisories"]) and item["advisories"] != prior_advisories
        checked_at_text = item.get("last_review_checked_at") or (previous or {}).get("created_at")
        checked_at = datetime.fromisoformat(checked_at_text) if checked_at_text else None
        weekly_due = checked_at is None or now - checked_at >= REVIEW_INTERVAL
        if (item["relationship"] == "direct" and weekly_due) or new_advisory:
            due.append(item["entry_path"])
    if not due:
        return {"due": 0, "new_evidence": 0, "unchanged": 0, "failed": 0}
    hosted_source = _hosted_pulls(project_id)
    result = {"due": len(due), "new_evidence": 0, "unchanged": 0, "failed": 0}
    for entry_path in due:
        try:
            review = review_dependency(project_id, entry_path, hosted_source=hosted_source)
        except (ValueError, OSError):
            result["failed"] += 1
            continue
        result["new_evidence" if review["new_evidence"] else "unchanged"] += 1
    return result


def record_decision(
    project_id: str, entry_path: str, *, decision: str,
    rationale: str, expected_revision: int,
    recommended_version: str | None = None, queue_task: bool = False,
) -> dict[str, Any]:
    """Save an explicit decision against the reviewed evidence revision."""
    previous = dependency_reviews.latest(project_id, entry_path)
    reason = rationale.strip()
    retry_queued_update = bool(
        previous
        and queue_task
        and decision == "update"
        and previous["revision"] == expected_revision + 1
        and previous["decision"] == "update"
        and previous["recommended_version"] == recommended_version
        and previous["rationale"] == reason
    )
    if previous is None or (previous["revision"] != expected_revision and not retry_queued_update):
        raise ValueError("Review changed; refresh the decision packet before recording")
    if decision not in {"update", "hold", "investigate"}:
        raise ValueError("Decision must be update, hold, or investigate")
    if not reason:
        raise ValueError("A reason is required")
    if decision == "update" and not recommended_version:
        raise ValueError("An update decision requires a recommended version")
    if queue_task and decision != "update":
        raise ValueError("Only a justified update can queue work")
    if retry_queued_update:
        record = previous
    else:
        record, _ = dependency_reviews.append(
            project_id, entry_path, evidence_hash=previous["evidence_hash"],
            evidence=previous["evidence"], decision=decision,
            recommended_version=recommended_version if decision == "update" else None,
            rationale=reason,
            expected_revision=expected_revision,
        )
    if queue_task:
        if record.get("task_id"):
            return record
        from ..storage.tasks.core import create_task

        name = record["evidence"]["inventory"]["name"]
        identity_key = f"{project_id}:{entry_path}:{recommended_version}"
        task = create_task(
            project_id, f"Update {name} to {recommended_version}",
            description=(
                f"Dependency decision revision {record['revision']} for {entry_path}. "
                f"Reason: {reason}. Review evidence before changing lockfiles."
            ),
            labels=["dependencies"],
            external_identity={
                "principal_scope": project_id,
                "external_origin": "dependency-review",
                "external_request_key": identity_key,
                "external_payload_digest": hashlib.sha256(identity_key.encode()).hexdigest(),
            },
        )
        record = dependency_reviews.attach_task(project_id, entry_path, record["id"], task["id"])
    return record
