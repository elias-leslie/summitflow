"""Retained publication findings and project-owned repair work."""
from __future__ import annotations

import os
import re
import subprocess
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ...config import DATABASE_URL
from ...utils import safe_subprocess
from .columns import TASK_COLUMNS_WITH_SPIRIT
from .core import create_task
from .mapping import row_to_dict_with_spirit

REPAIR_LABEL = "publication-repair"
_POLICY_APPROVER = "owner-approved-local-repair-policy"
_SOURCE_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _ensure_policy_plan(task_id: str) -> None:
    """Recover interrupted factory setup without rewriting an owner's later plan."""
    from ..subtasks import create_subtask, get_subtasks_for_task
    from ..task_spirit import approve_plan, get_task_spirit

    spirit = get_task_spirit(task_id) or {}
    if not (spirit.get("context") or {}).get("publication_repair"):
        return
    fresh = not spirit.get("plan_history")
    if not fresh and not (spirit.get("plan_status") == "approved" and spirit.get("plan_approved_by") == _POLICY_APPROVER):
        return
    if not get_subtasks_for_task(task_id):
        create_subtask(
            task_id, "1.1",
            "Inspect retained source-bound findings, repair their causes and any demonstrated workflow gaps, "
            "add focused regression coverage, and run canonical local acceptance. Submit the accepted "
            "repair with local acceptance and any explicit runtime evidence. Publication is independent.",
            display_order=0, phase="implementation",
        )
    if fresh and spirit.get("plan_status") != "approved":
        approve_plan(task_id, approved_by=_POLICY_APPROVER)


def unresolved_repair(task: dict[str, Any]) -> list[str]:
    if REPAIR_LABEL not in (task.get("labels") or []):
        return []
    findings = (task.get("verification_result") or {}).get("publication_repair") or {}
    return [key for key, finding in findings.items()
            if isinstance(finding, dict) and finding_actionable(finding)]


def get_repair_task(project_id: str, *, connection: psycopg.Connection | None = None) -> dict[str, Any] | None:
    from ..connection import get_cursor
    with (connection.cursor() if connection else get_cursor()) as cur:
        cur.execute(f"""SELECT {TASK_COLUMNS_WITH_SPIRIT} FROM tasks t
                       LEFT JOIN task_spirit ts ON ts.task_id = t.id
                       WHERE t.project_id = %s AND t.labels @> %s::text[]
                       AND t.status NOT IN ('completed', 'cancelled') ORDER BY t.created_at, t.id LIMIT 1""",
                    (project_id, [REPAIR_LABEL]))
        row = cur.fetchone()
    return row_to_dict_with_spirit(row) if row else None


def _resolution_includes_failure(project_id: str, previous: dict[str, Any], observation: dict[str, Any],
                                 connection: psycopg.Connection) -> bool:
    """Prove inclusion of the actual failed source, never a current-HEAD guess."""
    failed = previous.get("source_commit")
    verified = observation.get("source_commit")
    if (not isinstance(failed, str) or not isinstance(verified, str)
            or not _SOURCE_OID.fullmatch(failed) or not _SOURCE_OID.fullmatch(verified)):
        return False
    if failed == verified:
        return True
    from ..projects import get_project_root_path

    root = get_project_root_path(project_id, connection=connection)
    if not root:
        return False
    # Remote merge objects may not exist locally. Missing proof retains the
    # finding; this read must not fetch or inspect another ambient Git repo.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_NO_LAZY_FETCH="1", GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        return safe_subprocess.run(
            ["git", "--no-replace-objects", "-C", root, "merge-base", "--is-ancestor", failed, verified],
            env=environment, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=10,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def record_finding(project_id: str, category: str, observation: dict[str, Any], *, resolved: bool,
                   resolution_reasons: frozenset[str] | None = None) -> str | None:
    """Serialize task creation and merge a category without overwriting independent evidence."""
    # Do not hold a pooled slot while the canonical task/spirit APIs use the
    # pool: concurrent project observations would exhaust it and deadlock.
    assert DATABASE_URL is not None
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("publication-repair:" + project_id,))
        task = get_repair_task(project_id, connection=conn)
        if task is None:
            if resolved:
                return None
            task = create_task(
                project_id=project_id, title="Investigate retained publication and secure-code findings",
                description=("Investigate retained source-bound findings and repair demonstrated product/security defects. "
                             "Use normal ST pickup and local checkpoints; preserve backups and unrelated work. "
                             "Do not weaken checks, disable hooks, change visibility, or enable autonomous execution. "
                             "Repair process defects that caused the failure. Closure requires relevant local acceptance "
                             "and explicit task runtime evidence; publication is independent."),
                priority=1, task_type="bug", complexity="STANDARD", execution_mode="manual",
                labels=[REPAIR_LABEL], initial_spirit={
                    "complexity": "STANDARD", "context": {"publication_repair": True},
                    "done_when": ["All retained actionable findings are resolved with evidence.",
                                  "Canonical local acceptance passes for the repair source.",
                                  "Required local and runtime evidence is retained; no gate was bypassed."],
                },
            )
        _ensure_policy_plan(task["id"])
        observed_at = observation.get("observed_at")
        try:
            timestamp = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("observation timezone required")
        except (TypeError, ValueError):
            if resolved:
                raise ValueError("Resolution requires a timestamped observation") from None
            timestamp = datetime.now(UTC)
        previous = ((task.get("verification_result") or {}).get("publication_repair") or {}).get(category) or {}
        # A narrow cause-specific resolution must not clear other policy or
        # coverage findings sharing the category. The exact previous category
        # remains covered by the source proof and compare-and-swap below.
        if resolved and resolution_reasons is not None and previous.get("reason") not in resolution_reasons:
            return str(task["id"])
        if previous.get("observed_at"):
            previous_time = datetime.fromisoformat(previous["observed_at"])
            # Equal timestamps prefer the failure: callbacks can arrive in
            # either order and an older success must never clear a newer defect.
            if timestamp < previous_time or (timestamp == previous_time and resolved and previous.get("state") != "resolved"):
                return str(task["id"])
        if (resolved and previous and previous.get("state") != "resolved"
                and not _resolution_includes_failure(project_id, previous, observation, conn)):
            return str(task["id"])
        # The advisory lock serializes observer callbacks. Compare the exact
        # category too: another task writer may replace it while Git proves
        # ancestry, and that replacement must not inherit the old proof.
        cur.execute("""UPDATE tasks SET verification_result = jsonb_set(
                       COALESCE(verification_result, '{}'::jsonb), '{publication_repair}',
                       COALESCE(verification_result->'publication_repair', '{}'::jsonb) || %s::jsonb),
                       updated_at = NOW() WHERE id = %s AND project_id = %s
                       AND COALESCE(verification_result->'publication_repair'->%s, '{}'::jsonb) = %s::jsonb""",
                    (Jsonb({category: {**observation, "observed_at": timestamp.astimezone(UTC).isoformat(),
                                      "state": "resolved" if resolved else "unresolved"}}),
                     task["id"], project_id, category, Jsonb(previous)))
        return str(task["id"])


_ADMINISTRATIVE_REASONS = frozenset({"cloud_ci_missing", "outside_publication_window",
    "outside_nightly_window", "nightly_repair_confirmation_pending"})


def finding_actionable(finding: dict[str, Any]) -> bool:
    if finding.get("state") == "resolved":
        return False
    disposition = finding.get("disposition") or {}
    return not (disposition.get("kind") == "publication_disposition.v1"
                and disposition.get("classification") == "administrative"
                and disposition.get("state") == "no_longer_required"
                and finding.get("reason") in _ADMINISTRATIVE_REASONS
                and disposition.get("prior_finding") == {key: value for key, value in finding.items() if key != "disposition"})


def classify_retained_finding(category: str, finding: dict[str, Any]) -> str:
    """Classify administration narrowly; remote failures need investigation."""
    if finding.get("reason") in _ADMINISTRATIVE_REASONS:
        return "administrative"
    if category in {"codeql", "outgoing_security"}:
        return "security_investigation"
    return "investigation"


def disposition_finding(task_id: str, project_id: str, category: str, *,
                        expected_finding: dict[str, Any], classification: str,
                        reason: str, evidence: str) -> bool:
    """Owner operation: compare the full finding and retain truthful disposition."""
    if classification not in {"administrative", "product_defect", "security_investigation", "investigation"}:
        raise ValueError("Unknown finding classification")
    if not reason.strip() or not evidence.strip():
        raise ValueError("Disposition requires an owner reason and evidence reference")
    if classification == "administrative" and expected_finding.get("reason") not in _ADMINISTRATIVE_REASONS:
        raise ValueError("A product/security or untriaged failure cannot be retired as administration")
    if expected_finding.get("state") == "resolved":
        return False
    from ..connection import get_connection
    disposition = {"kind": "publication_disposition.v1", "classification": classification,
        "state": "no_longer_required" if classification == "administrative" else "actionable",
        "reason": reason, "evidence": evidence, "observed_at": datetime.now(UTC).isoformat(),
        "prior_finding": expected_finding}
    updated = {**expected_finding, "disposition": disposition}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE tasks SET verification_result = jsonb_set(
            COALESCE(verification_result, '{}'::jsonb), ARRAY['publication_repair', %s], %s::jsonb),
            updated_at = NOW() WHERE id = %s AND project_id = %s
            AND verification_result->'publication_repair'->%s = %s::jsonb""",
            (category, Jsonb(updated), task_id, project_id, category, Jsonb(expected_finding)))
        changed = cur.rowcount == 1
        conn.commit()
    return changed
