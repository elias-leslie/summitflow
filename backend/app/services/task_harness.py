"""Shared task harness routing and execution-contract helpers."""

from __future__ import annotations

from typing import Any

from ._task_harness_contract import (
    estimate_prompt_tokens,
    normalize_execution_contract,
    summarize_execution_contract,
)
from ._task_harness_routing import (
    HarnessRouteDecision,
    _get_context,
    determine_task_harness,
)

__all__ = [
    "HarnessRouteDecision",
    "apply_execution_contract_defaults",
    "determine_task_harness",
    "estimate_prompt_tokens",
    "execution_contract_issues",
    "normalize_execution_contract",
    "summarize_execution_contract",
]


def execution_contract_issues(
    decision: HarnessRouteDecision,
    value: Any,
) -> tuple[list[str], list[str]]:
    """Return (issues, missing_fields) for runtime-eval contract requirements."""
    if not decision.requires_execution_contract:
        return [], []

    contract = normalize_execution_contract(value, default_mode=decision.mode)
    if not contract:
        return ["Missing execution contract for runtime-evaluated task"], ["execution_contract"]

    issues: list[str] = []
    missing_fields: list[str] = []

    if not contract.get("target_urls"):
        issues.append("Execution contract missing target_urls")
        missing_fields.append("execution_contract")

    has_checks = (
        contract.get("user_flows")
        or contract.get("api_checks")
        or contract.get("negative_cases")
    )
    if not has_checks:
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
    spirit_like: dict[str, Any] = (
        {"context": dict(context)} if isinstance(context, dict) else {"context": {}}
    )
    if "execution_contract" in enriched:
        spirit_context = _get_context(spirit_like)
        spirit_context["execution_contract"] = enriched.get("execution_contract")

    merged_task = dict(task)
    if enriched.get("complexity"):
        merged_task["complexity"] = enriched["complexity"]

    subtasks = enriched.get("subtasks")
    decision = determine_task_harness(
        merged_task,
        spirit_like,
        subtasks if isinstance(subtasks, list) else [],
    )
    contract = normalize_execution_contract(
        enriched.get("execution_contract"),
        default_mode=decision.mode if decision.mode != "code_only" else None,
    )
    if contract:
        enriched["execution_contract"] = contract
    elif decision.mode != "code_only":
        enriched["execution_contract"] = {"mode": decision.mode}
    return enriched
