"""Compatibility exports for st-owned Jujutsu workflows."""

from __future__ import annotations

import subprocess  # noqa: F401 - public patch surface for legacy tests/callers.

from .jj_common import (
    CURRENT_REV_TEMPLATE,
    JJ_GLOBAL_ARGS,
    JJ_TIMEOUT_SECONDS,
    LOG_TEMPLATE,
    OP_LOG_TEMPLATE,
    JJError,
    JJRepoStatus,
    JJRevisionInfo,
    current_git_repo,
    is_colocated,
    jj_binary,
    require_success,
    run_git,
    run_jj,
)
from .jj_publish import (
    commit_current_revision,
    commit_selected_paths,
    delete_task_bookmark,
    publish_current_revision,
    task_bookmark,
)
from .jj_status import (
    current_revision_info,
    display_branch,
    format_status_line,
    init_colocated,
    latest_operation_id,
    revision_info,
    run_checks,
    status_summary,
    unpublished_count,
)

__all__ = [
    "CURRENT_REV_TEMPLATE",
    "JJ_GLOBAL_ARGS",
    "JJ_TIMEOUT_SECONDS",
    "LOG_TEMPLATE",
    "OP_LOG_TEMPLATE",
    "JJError",
    "JJRepoStatus",
    "JJRevisionInfo",
    "commit_current_revision",
    "commit_selected_paths",
    "current_git_repo",
    "current_revision_info",
    "delete_task_bookmark",
    "display_branch",
    "format_status_line",
    "init_colocated",
    "is_colocated",
    "jj_binary",
    "latest_operation_id",
    "publish_current_revision",
    "require_success",
    "revision_info",
    "run_checks",
    "run_git",
    "run_jj",
    "status_summary",
    "task_bookmark",
    "unpublished_count",
]
