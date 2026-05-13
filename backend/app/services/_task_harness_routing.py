"""Task harness routing: signal detection and mode determination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._task_harness_contract import normalize_execution_contract

_VALID_HARNESS_MODES = {"code_only", "runtime_eval", "runtime_eval_plus_design"}


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


def _get_context(spirit: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(spirit, dict):
        return {}
    context = spirit.get("context")
    return context if isinstance(context, dict) else {}


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
    has_runtime_signals = bool(
        contract.get("target_urls")
        or contract.get("user_flows")
        or contract.get("api_checks")
        or contract.get("negative_cases")
    )

    if has_runtime_signals:
        mode = (
            contract_mode
            if contract_mode in _VALID_HARNESS_MODES and contract_mode != "code_only"
            else "runtime_eval"
        )
        return HarnessRouteDecision(
            mode=mode,
            reasons=["contract_runtime_signals"],
            requires_execution_contract=True,
            run_runtime_evaluator=True,
            run_design_critic=mode == "runtime_eval_plus_design" and bool(contract.get("design_criteria")),
        )

    return HarnessRouteDecision(mode="code_only")
