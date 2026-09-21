"""Canonical infrastructure backup coverage contract.

Single source of truth for what 'infrastructure backup' includes.
All health checks, UI copy, and restore validation reference this contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CoverageComponent:
    """One component of the infrastructure backup contract."""

    key: str
    label: str
    category: str  # "required" | "optional" | "excluded"
    description: str
    archive_marker: str | None = None
    reason: str | None = None


INFRA_COVERAGE: tuple[CoverageComponent, ...] = (
    CoverageComponent(
        key="postgres_dump",
        label="PostgreSQL dump",
        category="required",
        description="Full logical dump of all databases and roles (pg_dumpall)",
        archive_marker="pgdumpall.sql.gz",
    ),
    CoverageComponent(
        key="env_local",
        label="Global secrets",
        category="required",
        description="~/.env.local — passwords, API keys, DB URLs",
        archive_marker="configs/env.local",
    ),
    CoverageComponent(
        key="compose_env",
        label="Docker compose env",
        category="required",
        description="docker/compose/.env — container configuration and credentials",
        archive_marker="configs/compose-env",
    ),
    CoverageComponent(
        key="smb_credentials",
        label="SMB credentials",
        category="required",
        description="~/.smbcredentials — backup storage access",
        archive_marker="configs/smbcredentials",
    ),
    CoverageComponent(
        key="hatchet_config",
        label="Hatchet config",
        category="required",
        description="docker/compose/hatchet-config — workflow engine signing keys and config",
        archive_marker="configs/hatchet-config",
    ),
    CoverageComponent(
        key="redis_state",
        label="Redis state",
        category="required",
        description="Redis RDB snapshot — cached state and session data",
        archive_marker="configs/redis-dump.rdb",
    ),
    CoverageComponent(
        key="host_ingress",
        label="Host ingress configuration",
        category="required",
        description="Cloudflared and Caddy configuration plus host-held credentials",
        archive_marker="state/host-ingress/manifest.json",
    ),
    CoverageComponent(
        key="systemd_user",
        label="User service state",
        category="required",
        description="User systemd unit files and enablement link identities",
        archive_marker="state/systemd-user/manifest.json",
    ),
    CoverageComponent(
        key="agent_hub_state",
        label="Agent Hub durable state",
        category="required",
        description="Agent Hub context-delivery evidence, adapter backups, and journals",
        archive_marker="state/agent-hub/manifest.json",
    ),
    CoverageComponent(
        key="managed_service_state",
        label="Managed service evidence",
        category="required",
        description="Deployment receipts, jobs, and current/previous release identities",
        archive_marker="state/managed-services/manifest.json",
    ),
    CoverageComponent(
        key="pg_basebackup",
        label="Physical base backup",
        category="excluded",
        description="pg_basebackup for point-in-time recovery",
        reason="Not needed — daily pg_dumpall backups provide sufficient recovery",
    ),
)


def get_infra_coverage_contract() -> list[dict[str, Any]]:
    """Return the full coverage contract as serializable dicts."""
    return [
        {
            "key": c.key,
            "label": c.label,
            "category": c.category,
            "description": c.description,
            "archive_marker": c.archive_marker,
            "reason": c.reason,
        }
        for c in INFRA_COVERAGE
    ]


@dataclass
class ComponentResult:
    """Result of checking one component against an archive."""

    key: str
    label: str
    category: str
    present: bool
    error: str | None = None


@dataclass
class CoverageResult:
    """Result of verifying an archive against the coverage contract."""

    complete: bool
    required_count: int
    present_count: int
    missing: list[str]
    components: list[ComponentResult]


def _parse_tree_context(
    verification_json: dict[str, Any] | None,
) -> tuple[set[str], bool]:
    """Extract tree-matching signals from verification_json.

    Returns:
        (tree_keys, has_db)
    """
    tree = verification_json.get("tree", {}) if verification_json else {}
    tree_keys = set(tree.keys()) if tree else set()
    has_db = verification_json.get("has_db", False) if verification_json else False

    return tree_keys, has_db


def _marker_present(
    marker: str,
    tree_keys: set[str],
    has_db: bool,
) -> bool:
    """Determine whether an exact top-level archive marker is present.

    Nested markers require explicit per-component capture evidence. The archive
    tree stores only top-level counts, which cannot prove any individual file.
    """
    if marker == "pgdumpall.sql.gz":
        return has_db or marker in tree_keys
    if "/" in marker:
        return False

    return marker in tree_keys


def _check_component(
    comp: CoverageComponent,
    tree_keys: set[str],
    has_db: bool,
    capture_components: dict[str, Any] | None = None,
) -> ComponentResult:
    """Evaluate a single coverage component and return its result."""
    if comp.category == "excluded" or comp.archive_marker is None:
        return ComponentResult(
            key=comp.key, label=comp.label, category=comp.category,
            present=False,
        )

    captured = (capture_components or {}).get(comp.key)
    if isinstance(captured, dict):
        status = captured.get("status")
        present = status == "captured"
        captured_error = captured.get("error")
        error = (
            str(captured_error)
            if not present and isinstance(captured_error, str) and captured_error
            else f"{comp.label} capture status: {status or 'unknown'}"
            if not present and comp.category == "required"
            else None
        )
        return ComponentResult(
            key=comp.key,
            label=comp.label,
            category=comp.category,
            present=present,
            error=error,
        )

    present = _marker_present(comp.archive_marker, tree_keys, has_db)
    error = (
        f"{comp.label} not found in archive"
        if not present and comp.category == "required"
        else None
    )
    return ComponentResult(
        key=comp.key, label=comp.label, category=comp.category,
        present=present, error=error,
    )


def _tally_required(components: list[ComponentResult]) -> tuple[int, int, list[str]]:
    """Count required components and collect missing keys.

    Returns:
        (required_count, present_count, missing_keys)
    """
    required_count = 0
    present_count = 0
    missing: list[str] = []

    for c in components:
        if c.category != "required":
            continue
        required_count += 1
        if c.present:
            present_count += 1
        else:
            missing.append(c.key)

    return required_count, present_count, missing


def verify_archive_coverage(verification_json: dict[str, Any] | None) -> CoverageResult:
    """Check an archive's verification data against the coverage contract.

    Args:
        verification_json: The verification_json from a backup record,
            containing a 'tree' dict of archive contents.

    Returns:
        CoverageResult with per-component pass/fail.
    """
    tree_keys, has_db = _parse_tree_context(verification_json)
    coverage = verification_json.get("coverage", {}) if verification_json else {}
    capture_components = coverage.get("components", {}) if isinstance(coverage, dict) else {}
    if not isinstance(capture_components, dict):
        capture_components = {}

    components = [
        _check_component(
            comp,
            tree_keys,
            has_db,
            capture_components,
        )
        for comp in INFRA_COVERAGE
    ]

    required_count, present_count, missing = _tally_required(components)

    return CoverageResult(
        complete=present_count == required_count,
        required_count=required_count,
        present_count=present_count,
        missing=missing,
        components=components,
    )


def get_coverage_summary(verification_json: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a coverage summary suitable for API responses.

    Args:
        verification_json: If provided, includes verification results.
            If None, returns contract-only summary.
    """
    contract = get_infra_coverage_contract()

    if verification_json is None:
        return {
            "contract": contract,
            "verified": False,
            "result": None,
        }

    result = verify_archive_coverage(verification_json)
    return {
        "contract": contract,
        "verified": True,
        "result": {
            "complete": result.complete,
            "required_count": result.required_count,
            "present_count": result.present_count,
            "missing": result.missing,
            "components": [
                {
                    "key": c.key,
                    "label": c.label,
                    "category": c.category,
                    "present": c.present,
                    "error": c.error,
                }
                for c in result.components
            ],
        },
    }
