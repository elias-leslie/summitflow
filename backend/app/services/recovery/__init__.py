"""Recovery system for TDD build failures.

This package provides failure classification, circular fix detection,
and recovery strategies for the TDD build loop.
"""

from .circular import is_circular_fix
from .classifier import FailureType, RecoveryStrategy, classify_failure

__all__ = [
    "FailureType",
    "RecoveryStrategy",
    "classify_failure",
    "is_circular_fix",
]
