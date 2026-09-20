"""Compatibility alias for public ST SDK execution-context helpers."""

from __future__ import annotations

import sys

from st_sdk import execution_context as _implementation
from st_sdk.execution_context import canonical_repo_root as canonical_repo_root
from st_sdk.execution_context import resolve_checkout_project_id as resolve_checkout_project_id
from st_sdk.execution_context import resolve_checkout_root as resolve_checkout_root
from st_sdk.execution_context import resolve_git_common_dir as resolve_git_common_dir

__all__ = [
    "canonical_repo_root",
    "resolve_checkout_project_id",
    "resolve_checkout_root",
    "resolve_git_common_dir",
]

sys.modules[__name__] = _implementation
