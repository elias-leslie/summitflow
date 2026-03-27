"""Execution-contract normalization and validation helpers."""

from __future__ import annotations

from math import ceil
from typing import Any, cast

_VALID_HARNESS_MODES = {"code_only", "runtime_eval", "runtime_eval_plus_design"}


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _normalize_contract_checks(items: Any, prefix: str) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        item_data = cast(dict[str, Any], item)
        entry: dict[str, Any] = {
            key: val for key, val in item_data.items() if val not in (None, "", [], {})
        }
        entry["criterion_id"] = _clean_text(entry.get("criterion_id")) or f"{prefix}-{index}"
        if method := _clean_text(entry.get("method")):
            entry["method"] = method.upper()
        if body_expectations := _clean_string_list(entry.get("body_expectations")):
            entry["body_expectations"] = body_expectations
        normalized.append(entry)
    return normalized


def _normalize_user_flows(flows: Any) -> list[dict[str, Any]]:
    if not isinstance(flows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, flow in enumerate(flows, start=1):
        if not isinstance(flow, dict):
            continue
        flow_data = cast(dict[str, Any], flow)
        title = _clean_text(flow_data.get("title"))
        actions = _clean_string_list(flow_data.get("actions"))
        expected_outcomes = _clean_string_list(flow_data.get("expected_outcomes"))
        if not title and not actions and not expected_outcomes:
            continue
        entry: dict[str, Any] = {
            "flow_id": _clean_text(flow_data.get("flow_id")) or f"flow-{index}",
            "title": title or f"Flow {index}",
            "setup": _clean_string_list(flow_data.get("setup")),
            "actions": actions,
            "expected_outcomes": expected_outcomes,
        }
        if target_url := _clean_text(flow_data.get("target_url")):
            entry["target_url"] = target_url
        normalized.append(entry)
    return normalized


def normalize_execution_contract(
    value: Any,
    *,
    default_mode: str | None = None,
) -> dict[str, Any]:
    """Normalize execution-contract payloads into a stable JSON-friendly shape."""
    if not isinstance(value, dict):
        if default_mode in _VALID_HARNESS_MODES and default_mode != "code_only":
            return {"mode": default_mode}
        return {}

    mode = _clean_text(value.get("mode"))
    if mode not in _VALID_HARNESS_MODES:
        mode = default_mode if default_mode in _VALID_HARNESS_MODES else None

    contract: dict[str, Any] = {}
    if mode:
        contract["mode"] = mode
    if target_urls := _clean_string_list(value.get("target_urls")):
        contract["target_urls"] = target_urls
    if user_flows := _normalize_user_flows(value.get("user_flows")):
        contract["user_flows"] = user_flows
    if api_checks := _normalize_contract_checks(value.get("api_checks"), "api"):
        contract["api_checks"] = api_checks
    if negative_cases := _normalize_contract_checks(value.get("negative_cases"), "negative"):
        contract["negative_cases"] = negative_cases
    if evidence := _clean_string_list(value.get("evidence_requirements")):
        contract["evidence_requirements"] = evidence
    design_criteria = value.get("design_criteria")
    if isinstance(design_criteria, dict) and design_criteria:
        contract["design_criteria"] = design_criteria
    if risk_notes := _clean_string_list(value.get("risk_notes")):
        contract["risk_notes"] = risk_notes

    return contract


def summarize_execution_contract(value: Any) -> dict[str, Any]:
    """Return compact execution-contract counts for display surfaces."""
    contract = normalize_execution_contract(value)
    return {
        "mode": contract.get("mode") or "code_only",
        "target_url_count": len(contract.get("target_urls") or []),
        "user_flow_count": len(contract.get("user_flows") or []),
        "api_check_count": len(contract.get("api_checks") or []),
        "negative_case_count": len(contract.get("negative_cases") or []),
        "has_design_criteria": bool(contract.get("design_criteria")),
        "evidence_requirement_count": len(contract.get("evidence_requirements") or []),
    }


def estimate_prompt_tokens(text: str) -> int:
    """Estimate token usage with a cheap character-based heuristic."""
    return ceil(len(text) / 4) if text else 0
