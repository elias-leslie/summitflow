"""Task harness routing: signal detection and mode determination."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._task_harness_contract import normalize_execution_contract

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


def _collect_scope_files(spirit: dict[str, Any] | None) -> list[str]:
    from ._task_harness_contract import _clean_string_list

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


def _has_design_signal(
    task: dict[str, Any],
    paths: list[str],
    subtasks: list[dict[str, Any]],
    contract: dict[str, Any],
) -> bool:
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
        for part in [task.get("title", ""), task.get("description", ""), *paths]
        if part
    )
    return any(keyword in haystack for keyword in _DESIGN_KEYWORDS)


def _route_from_contract_mode(
    contract_mode: str,
    reasons: list[str],
) -> HarnessRouteDecision:
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
        return _route_from_contract_mode(contract_mode, reasons)

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

    needs_runtime = has_runtime_signals or (
        has_frontend and (task_type in _RUNTIME_TASK_TYPES or complexity in {"STANDARD", "COMPLEX"})
    )
    if needs_runtime:
        return HarnessRouteDecision(
            mode="runtime_eval",
            reasons=reasons or ["runtime_signals"],
            requires_execution_contract=True,
            run_runtime_evaluator=True,
        )

    return HarnessRouteDecision(mode="code_only", reasons=reasons)
