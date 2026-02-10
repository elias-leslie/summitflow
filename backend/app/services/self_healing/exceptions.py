"""Exceptions for self-healing orchestration."""

from __future__ import annotations

from .config import BUDGET_CAP_USD


class BudgetExceededError(Exception):
    """Raised when cumulative cost exceeds BUDGET_CAP_USD.

    This is a safety constraint that cannot be disabled or configured.
    When raised, the orchestrator should stop all fix attempts immediately.
    """

    def __init__(self, cumulative_cost: float, budget: float = BUDGET_CAP_USD):
        self.cumulative_cost = cumulative_cost
        self.budget = budget
        super().__init__(
            f"Budget exceeded: ${cumulative_cost:.4f} >= ${budget:.2f}. "
            "Stopping autonomous fixes to prevent runaway costs."
        )
