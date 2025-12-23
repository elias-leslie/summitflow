"""Recovery system for TDD build failures.

This package provides failure classification, circular fix detection,
and recovery strategies for the TDD build loop.
"""

from .circular import is_circular_fix
from .classifier import FailureType, RecoveryStrategy, classify_failure
from .manager import RecoveryManager, rollback_to_commit

__all__ = [
    "FailureType",
    "RecoveryManager",
    "RecoveryStrategy",
    "classify_failure",
    "is_circular_fix",
    "rollback_to_commit",
]
