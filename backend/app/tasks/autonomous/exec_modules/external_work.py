"""Deterministic verification for work completed outside the checkout.

External work is accepted only when the task's retained external identity is
verified by the fixed Agent Hub maintenance endpoint.  Task text and origin
labels are never sufficient evidence.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from cli.lib.checkpoint import get_active_checkpoints

from ....services._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers
from ..pickup_guards import _HTTP_TIMEOUT

_EXTERNAL_ORIGIN = "agent-hub-context-maintenance"
_VERIFY_PATH = "/api/runtime-context/manage/maintenance"
_REQUEST_KEY = re.compile(
    r"^(?P<item>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})"
    r"(?::generation-(?P<generation>[1-9][0-9]*))?$"
)


def _build_internal_agent_hub_headers() -> dict[str, str] | None:
    """Build the approved internal header without exposing its value."""
    secret = os.getenv("INTERNAL_SERVICE_SECRET", "").strip()
    if not secret:
        return None
    return build_agent_hub_headers(
        request_source="summitflow-context-maintenance",
        extra_headers={"X-Agent-Hub-Internal": secret},
    )


@dataclass(frozen=True)
class ExternalWorkResult:
    """Compact, typed result for a canonical external-work receipt."""

    verified: bool
    reason: str
    receipt: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.verified and self.receipt is not None

    def step_result(self) -> dict[str, Any]:
        return {
            "step_number": 0,
            "passed": self.passed,
            "reason": "external_work_verified" if self.passed else "external_work_unverified",
            "output": self.reason,
            **({"external_work": self.receipt} if self.receipt else {}),
            "returncode": 0 if self.passed else 1,
        }


def _identity(task: dict[str, Any]) -> tuple[str, int, str, str] | None:
    if (
        task.get("external_origin") != _EXTERNAL_ORIGIN
        or task.get("project_id") != "agent-hub"
        or not str(task.get("id") or "").strip()
    ):
        return None
    request_key = str(task.get("external_request_key") or "")
    match = _REQUEST_KEY.fullmatch(request_key)
    digest = str(task.get("external_payload_digest") or "")
    if not match or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
        return None
    try:
        item_id = str(UUID(match.group("item")))
    except ValueError:
        return None
    generation = int(match.group("generation") or 0)
    return item_id, generation, request_key, digest


def _invalid(reason: str) -> ExternalWorkResult:
    return ExternalWorkResult(False, reason)


def verify_external_work(task: dict[str, Any]) -> ExternalWorkResult:
    """Verify a retained maintenance receipt without invoking a model."""
    identity = _identity(task)
    if identity is None:
        return _invalid("external_work_identity_missing_or_malformed")

    item_id, generation, request_key, payload_digest = identity
    payload = {
        "action": "verify_work",
        "context": {"consumer_surface": "agent_runtime", "project_id": "agent-hub"},
        "item_id": item_id,
        "generation": generation,
        "task_id": str(task.get("id") or ""),
        "external_request_key": request_key,
        "external_payload_digest": payload_digest,
    }
    headers = _build_internal_agent_hub_headers()
    if headers is None:
        return _invalid("agent_hub_internal_auth_unavailable")
    url = f"{AGENT_HUB_URL.rstrip('/')}{_VERIFY_PATH}"
    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=_HTTP_TIMEOUT,
        )
        if response.status_code >= 400:
            return _invalid(f"agent_hub_verify_http_{response.status_code}")
        result = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return _invalid(f"agent_hub_verify_unavailable:{type(exc).__name__}")

    if not isinstance(result, dict):
        return _invalid("agent_hub_verify_malformed_response")
    if result.get("verified") is not True:
        return _invalid(str(result.get("reason") or "canonical_receipt_not_verified"))
    if result.get("verification") != "canonical_generation":
        return _invalid("canonical_verification_marker_missing")
    if str(result.get("item_id") or "") != item_id:
        return _invalid("canonical_receipt_item_mismatch")
    if str(result.get("task_id") or "") != str(task.get("id") or ""):
        return _invalid("canonical_receipt_task_mismatch")
    if str(result.get("external_request_key") or "") != request_key:
        return _invalid("canonical_receipt_request_key_mismatch")
    if str(result.get("external_payload_digest") or "") != payload_digest:
        return _invalid("canonical_receipt_payload_digest_mismatch")
    if "generation" in result and result.get("generation") != generation:
        return _invalid("canonical_receipt_generation_mismatch")
    if (
        isinstance(result.get("item_version"), bool)
        or not isinstance(result.get("item_version"), int)
        or result["item_version"] < 1
    ):
        return _invalid("canonical_receipt_item_version_missing")
    if result.get("state") not in {"resolved", "dismissed"}:
        return _invalid("canonical_receipt_not_terminal")
    receipt_ids = (result.get("change_id"), result.get("event_id"))
    valid_ids = []
    for value in receipt_ids:
        if value is None:
            valid_ids.append(False)
            continue
        if not isinstance(value, str):
            return _invalid("canonical_receipt_change_or_event_malformed")
        try:
            UUID(value)
        except ValueError:
            return _invalid("canonical_receipt_change_or_event_malformed")
        valid_ids.append(True)
    if not any(valid_ids):
        return _invalid("canonical_receipt_change_or_event_missing")
    verified_sources = result.get("verified_sources")
    if (
        not isinstance(verified_sources, list)
        or not verified_sources
        or any(
            not isinstance(source, dict)
            or not all(
                isinstance(source.get(key), str) and source[key].strip()
                for key in ("source_type", "source_id", "revision")
            )
            for source in verified_sources
        )
    ):
        return _invalid("canonical_receipt_sources_missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(result.get("payload_hash") or "")):
        return _invalid("canonical_receipt_payload_hash_missing")
    receipt = {
        key: result[key]
        for key in (
            "verified", "reason", "item_id", "item_version", "task_id",
            "external_request_key", "external_payload_digest", "state",
            "change_id", "event_id", "verified_sources", "payload_hash",
            "verification",
        )
        if key in result
    }
    receipt["generation"] = generation
    return ExternalWorkResult(True, "canonical_external_work_verified", receipt)


def external_work_step(step_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a previously verified external receipt from step results."""
    for step in step_results:
        receipt = step.get("external_work") if isinstance(step, dict) else None
        if isinstance(receipt, dict) and step.get("passed") is True:
            return receipt
    return None


def external_work_receipt(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find a verified external receipt in completed subtask results."""
    for result in results:
        if not isinstance(result, dict):
            continue
        receipt = external_work_step(result.get("step_results") or [])
        if receipt is not None:
            return receipt
    return None


def checkout_is_clean_for_external_work(task: dict[str, Any], project_path: str) -> bool:
    """Require a retained checkpoint or execution-start baseline to be unchanged."""
    if _identity(task) is None:
        return False
    task_id = str(task.get("id") or "")
    project_id = str(task.get("project_id") or "")
    checkpoint = next(
        (entry for entry in get_active_checkpoints(project_id) if entry.task_id == task_id),
        None,
    )
    base_commit = str(getattr(checkpoint, "base_commit", "") or "")
    if not base_commit:
        from ....storage.task_spirit import get_task_spirit

        spirit = get_task_spirit(task_id) or {}
        context = spirit.get("context") if isinstance(spirit, dict) else None
        baseline = context.get("external_work_baseline") if isinstance(context, dict) else None
        base_commit = str(baseline.get("head") or "") if isinstance(baseline, dict) else ""
    if not base_commit:
        return False
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip():
            return False
        diff = subprocess.run(
            ["git", "diff", "--quiet", base_commit, "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return diff.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def is_external_work_candidate(task: dict[str, Any]) -> bool:
    """Return whether a task has the complete registered external identity."""
    return _identity(task) is not None


def capture_external_work_baseline(task: dict[str, Any], project_path: str) -> bool:
    """Persist a clean execution-start HEAD for autonomous external work."""
    if _identity(task) is None:
        return False
    task_id = str(task.get("id") or "")
    from ....storage.task_spirit import get_task_spirit, update_task_spirit

    spirit = get_task_spirit(task_id) or {}
    context = spirit.get("context") if isinstance(spirit, dict) else None
    context = dict(context) if isinstance(context, dict) else {}
    existing = context.get("external_work_baseline")
    if isinstance(existing, dict) and existing.get("head"):
        return True
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if status.returncode != 0 or status.stdout.strip() or head.returncode != 0:
            return False
        context["external_work_baseline"] = {
            "head": head.stdout.strip(),
            "source": "execution_start",
        }
        update_task_spirit(task_id, context=context)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


__all__ = [
    "ExternalWorkResult",
    "capture_external_work_baseline",
    "checkout_is_clean_for_external_work",
    "external_work_receipt",
    "external_work_step",
    "is_external_work_candidate",
    "verify_external_work",
]
