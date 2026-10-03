"""Owner-triggered exact-source publication through the existing isolated publisher.

No capture, commit, checkout reconciliation, deployment or schedule change occurs.
The existing source lease and genuine backup receipt own durable observations.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from ..services.publication_health import (
    get_project_publication_health,
    record_publication_observation,
)
from ..storage import backups as backup_store
from .backup_lock import acquire_backup_lock, maintain_backup_lock, owns_backup_lease
from .backup_publish import publish_source_before_backup

_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def publish_project_now(source_id: str, source_commit: str) -> dict[str, Any]:
    """Publish one explicitly requested, accepted commit without touching its checkout.

    This is the manual owner operation, not an automatic scheduling exception.
    A complete observation is merged into an existing real backup's publication
    slots so startup health and source-bound completion see the same evidence.
    """
    if not _OID.fullmatch(source_commit):
        raise ValueError("Publication requires an exact lowercase 40- or 64-character commit OID")
    result: dict[str, Any] = {
        "source_id": source_id,
        "publication_mode": "manual",
        "requested_source_commit": source_commit,
        "observed_at": datetime.now(UTC).isoformat(),
        "publication_complete": False,
        "evidence_recorded": False,
    }
    source = backup_store.get_source(source_id)
    if not source or not source.get("enabled") or source.get("source_type") != "project" or not source.get("project_id"):
        return {**result, "status": "failed", "reason": "enabled_project_source_required"}
    token = acquire_backup_lock(source_id)
    if token is None:
        return {**result, "status": "pending", "reason": "source_busy"}
    with maintain_backup_lock(source_id, token):
        latest = backup_store.get_latest_backup(source_id=source_id)
        if not latest:
            return {**result, "status": "pending", "reason": "publication_receipt_unavailable"}
        verification = latest.get("verification_json") or {}
        previous = verification.get("publish_before_backup") or verification.get("publication") or {}
        # Resume only this exact source. Never adopt an older observation's head.
        retained = previous if previous.get("head") == source_commit else None
        publication = publish_source_before_backup(
            source,
            retained=retained,
            manual_source_commit=source_commit,
            activity_allowed=lambda: owns_backup_lease(source_id, token),
        )
        result.update(publication)
        result["backup_id"] = str(latest["id"])
        if not owns_backup_lease(source_id, token):
            return {**result, "status": "pending", "reason": "source_busy", "publication_complete": False}
        persisted = backup_store.merge_backup_verification_json(str(latest["id"]), {
            "publication": publication,
            "publish_before_backup": publication,
        })
        if persisted is None:
            return {**result, "status": "pending", "reason": "publication_receipt_unavailable", "publication_complete": False}
        record_publication_observation(str(source["project_id"]), publication)
        result["evidence_recorded"] = True
        result["health"] = get_project_publication_health(str(source["project_id"]))
    return result
