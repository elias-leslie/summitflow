"""Quality gate services.

Provides fix agents for quality check failures and integration
with the orchestrator for auto-triggering fixes.
"""

from .escalation import MAX_FIX_ATTEMPTS, FixResult, escalate_to_human
from .fix_agent import fix_lint_type_error
from .orchestration import fix_unfixed_errors
from .test_fix_agent import (
    TestFixResult,
    fix_failing_tests,
    fix_test_failure,
)

__all__ = [
    "MAX_FIX_ATTEMPTS",
    "FixResult",
    "TestFixResult",
    "escalate_to_human",
    "fix_failing_tests",
    "fix_lint_type_error",
    "fix_test_failure",
    "fix_unfixed_errors",
]
