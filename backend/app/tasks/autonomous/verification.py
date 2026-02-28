"""Step verification for autonomous execution.

Re-exports smoke and targeted testing utilities.
"""

from __future__ import annotations

# Re-export smoke/targeted testing
from .smoke_testing import SmokeTestResult, TargetedTestResult, run_smoke_tests, run_targeted_tests

# Public API exports
__all__ = [
    "SmokeTestResult",
    "TargetedTestResult",
    "run_smoke_tests",
    "run_targeted_tests",
]
