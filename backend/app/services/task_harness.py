"""Shared task harness routing and execution-contract helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any, cast

_VALID_HARNESS_MODES = {"code_only", "runtime_eval", "runtime_eval_plus_design"}
_FRONTEND_SUFFIXES = (".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".html")
_DESIGN_KEYWORDS = (
    "design",
    "redesign",
    "visual",
    "layout",
    "ui",
    "ux",
    "styling",
    "mockup",
    "polish",
)
_RUNTIME_TASK_TYPES = {"feature", "task", "bug", "regression"}
_DESIGN_SUBTASK_TYPES = {"ui-design"}
_FRONTEND_SUBTASK_TYPES = {"frontend", *_DESIGN_SUBTASK_TYPES}


@dataclass(frozen=True)
class HarnessRouteDecision:
    """Centralized harness-routing result."""

    mode: str
    reasons: list[str] = field(default_factory=list)
    requires_execution_contract: bool = False
    run_runtime_evaluator: bool = False
    run_design_critic: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reasons": list(self.reasons),
            "requires_execution_contract": self.requires_execution_contract,
            "run_runtime_evaluator": self.run_runtime_evaluator,
            "run_design_critic": self.run_design_critic,
        }


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
            key: value for key, value in item_data.items() if value not in (None, "", [], {})
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
        entry = {
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


def _get_context(spirit: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(spirit, dict):
        return {}
    context = spirit.get("context")
    return context if isinstance(context, dict) else {}


def _collect_scope_files(spirit: dict[str, Any] | None) -> list[str]:
    context = _get_context(spirit)
    files: list[str] = []
    for key in ("files_to_modify", "files_to_create"):
        files.extend(_clean_string_list(context.get(key)))
    return files


def _has_frontend_scope(paths: list[str], subtasks: list[dict[str, Any]]) -> bool:
    if any(path.startswith("frontend/") or path.endswith(_FRONTEND_SUFFIXES) for path in paths):
        return True
    return any(
        str(subtask.get("subtask_type") or "").strip().lower() in _FRONTEND_SUBTASK_TYPES
        for subtask in subtasks
        if isinstance(subtask, dict)
    )


def _has_design_signal(task: dict[str, Any], paths: list[str], subtasks: list[dict[str, Any]], contract: dict[str, Any]) -> bool:
    if contract.get("design_criteria"):
        return True
    if any(
        str(subtask.get("subtask_type") or "").strip().lower() in _DESIGN_SUBTASK_TYPES
        for subtask in subtasks
        if isinstance(subtask, dict)
    ):
        return True
    haystack = " ".join(
        str(part).lower()
        for part in [
            task.get("title", ""),
            task.get("description", ""),
            *paths,
        ]
        if part
    )
    return any(keyword in haystack for keyword in _DESIGN_KEYWORDS)


def determine_task_harness(
    task: dict[str, Any] | None,
    spirit: dict[str, Any] | None = None,
    subtasks: list[dict[str, Any]] | None = None,
) -> HarnessRouteDecision:
    """Determine which harness mode a task should use."""
    task = task or {}
    spirit = spirit or {}
    subtasks = subtasks or []

    context = _get_context(spirit)
    contract = normalize_execution_contract(context.get("execution_contract"))
    contract_mode = contract.get("mode")
    paths = _collect_scope_files(spirit)
    has_frontend = _has_frontend_scope(paths, subtasks)
    has_design_signal = _has_design_signal(task, paths, subtasks, contract)
    has_runtime_signals = bool(
        contract.get("target_urls")
        or contract.get("user_flows")
        or contract.get("api_checks")
        or contract.get("negative_cases")
    )

    reasons: list[str] = []
    if contract_mode in _VALID_HARNESS_MODES:
        reasons.append("contract_mode_override")
        if contract_mode == "code_only":
            return HarnessRouteDecision(mode="code_only", reasons=reasons)
        return HarnessRouteDecision(
            mode=contract_mode,
            reasons=reasons,
            requires_execution_contract=True,
            run_runtime_evaluator=True,
            run_design_critic=contract_mode == "runtime_eval_plus_design",
        )

    if has_frontend:
        reasons.append("frontend_scope")
    if has_runtime_signals:
        reasons.append("contract_runtime_signals")
    if has_design_signal:
        reasons.append("design_sensitive")

    task_type = str(task.get("task_type") or "").strip().lower()
    complexity = str(task.get("complexity") or "SIMPLE").strip().upper()

    if has_design_signal and (has_frontend or has_runtime_signals):
        return HarnessRouteDecision(
            mode="runtime_eval_plus_design",
            reasons=reasons or ["design_sensitive"],
            requires_execution_contract=True,
            run_runtime_evaluator=True,
            run_design_critic=True,
        )

    if has_runtime_signals or (has_frontend and (task_type in _RUNTIME_TASK_TYPES or complexity in {"STANDARD", "COMPLEX"})):
        return HarnessRouteDecision(
            mode="runtime_eval",
            reasons=reasons or ["runtime_signals"],
            requires_execution_contract=True,
            run_runtime_evaluator=True,
        )

    return HarnessRouteDecision(mode="code_only", reasons=reasons)


def execution_contract_issues(
    decision: HarnessRouteDecision,
    value: Any,
) -> tuple[list[str], list[str]]:
    """Return (issues, missing_fields) for runtime-eval contract requirements."""
    if not decision.requires_execution_contract:
        return [], []

    contract = normalize_execution_contract(value, default_mode=decision.mode)
    issues: list[str] = []
    missing_fields: list[str] = []

    if not contract:
        return ["Missing execution contract for runtime-evaluated task"], ["execution_contract"]

    if not contract.get("target_urls"):
        issues.append("Execution contract missing target_urls")
        missing_fields.append("execution_contract")
    if not (
        contract.get("user_flows")
        or contract.get("api_checks")
        or contract.get("negative_cases")
    ):
        issues.append("Execution contract missing user_flows or API checks")
        if "execution_contract" not in missing_fields:
            missing_fields.append("execution_contract")
    if decision.run_design_critic and not contract.get("design_criteria"):
        issues.append("Execution contract missing design_criteria for design-sensitive task")
        if "execution_contract" not in missing_fields:
            missing_fields.append("execution_contract")

    return issues, missing_fields


def apply_execution_contract_defaults(
    task: dict[str, Any],
    plan_data: dict[str, Any],
) -> dict[str, Any]:
    """Default planner output to the inferred harness mode when useful."""
    enriched = dict(plan_data)
    context = enriched.get("context")
    spirit_like = {"context": dict(context)} if isinstance(context, dict) else {"context": {}}
    if "execution_contract" in enriched:
        spirit_like["context"]["execution_contract"] = enriched.get("execution_contract")
    merged_task = dict(task)
    if enriched.get("complexity"):
        merged_task["complexity"] = enriched["complexity"]

    decision = determine_task_harness(merged_task, spirit_like, enriched.get("subtasks") or [])
    contract = normalize_execution_contract(
        enriched.get("execution_contract"),
        default_mode=decision.mode if decision.mode != "code_only" else None,
    )
    if contract:
        enriched["execution_contract"] = contract
    elif decision.mode != "code_only":
        enriched["execution_contract"] = {"mode": decision.mode}
    return enriched
