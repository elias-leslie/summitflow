"""Quality gate checking and pristine codebase validation.

This module serves as a facade that re-exports functionality from:
- pristine: Pristine codebase checking and self-healing
- quality_gates: Quality gate checking functions
- quality_utils: Utility functions
"""

from __future__ import annotations

from .pristine import (
    PristineCheckError,
    check_pristine_codebase,
    pristine_self_heal,
)
from .quality_gates import (
    auto_fix_quality,
    run_final_quality_gate,
)
from .quality_utils import (
    find_check_tool,
    find_dev_tools,
    parse_error_count,
)

__all__ = [
    "PristineCheckError",
    "auto_fix_quality",
    "check_pristine_codebase",
    "find_check_tool",
    "find_dev_tools",
    "parse_error_count",
    "pristine_self_heal",
    "run_final_quality_gate",
]
