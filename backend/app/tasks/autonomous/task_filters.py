"""Task eligibility and exclusion filters for autonomous execution."""

from __future__ import annotations

import re
from typing import NotRequired, TypedDict

# Validation mode flags - disabled after phase 5 validation
AUTONOMOUS_DRY_RUN = False  # When True, log what would execute but don't actually run
VALIDATION_MODE = False  # When True, only execute tasks in ALLOWED_TASK_IDS
ALLOWED_TASK_IDS: list[str] = []  # Empty = no filter (when VALIDATION_MODE=True)

# Patterns in error titles that should NOT generate bug tasks.
# These cover environmental/transient issues, not actual code bugs.
ERROR_BLOCKLIST_PATTERNS = [
    "postgresql", "role.*does not exist", "database.*role",  # DB connection
    "authentication failure", "connection failed", "psql",
    "type error", "type mismatch", "type.check", "ty check",  # pre-existing type errors
    "typescript.*not found", "ts2307", "ts6053", "tsc", "module resolution",  # TS transient
    "missing from path", "cli missing", "command not found",  # missing tools
    "dependency", "package.json",
    "file not found", "test file", "migration inspection",  # transient test/build
    "jq filter", "jq syntax", "capability verification",
]

# Security-sensitive directory names that require human review
SECURITY_DIRS = ["auth", "security", "payment", "credentials", "secret", "crypto", "oauth"]

# Exploratory task indicators
EXPLORATORY_KEYWORDS = ["investigate", "explore", "understand", "research", "analyze"]

# Standalone task labels that require manual execution
STANDALONE_LABELS = ["standalone", "exploratory"]


class _PlanContext(TypedDict, total=False):
    affected_files: list[str]


class _PlanContent(TypedDict, total=False):
    context: _PlanContext


class TaskDict(TypedDict, total=False):
    """Minimal task fields used by eligibility filters."""

    task_type: str
    labels: list[str]
    capability_id: NotRequired[str | None]
    plan_content: _PlanContent
    tier: int
    title: str


def is_blocklisted_error(title: str) -> bool:
    """Check if error title matches blocklist patterns (environmental/transient issues)."""
    title_lower = title.lower()
    return any(re.search(pattern, title_lower) for pattern in ERROR_BLOCKLIST_PATTERNS)


def is_standalone(task: TaskDict) -> bool:
    """Check if task is standalone (no capability linkage), requiring manual execution.

    Exception: refactor/debt/regression types and auto-generated tasks use
    subtask+step verification and do not require capability linkage.
    """
    if task.get("task_type", "task") in ("refactor", "debt", "regression"):
        return False
    if "auto-generated" in (task.get("labels") or []):
        return False
    return task.get("capability_id") is None


def has_standalone_label(task: TaskDict) -> bool:
    """Check if task has a standalone or exploratory label."""
    return any(label in STANDALONE_LABELS for label in (task.get("labels") or []))


def _file_touches_security_dir(path: str) -> bool:
    """Return True if any path segment matches a security-sensitive directory."""
    return any(sec in part for part in path.lower().split("/") for sec in SECURITY_DIRS)


def is_security_sensitive(files: list[str]) -> bool:
    """Check if any files are in security-sensitive directories."""
    return any(_file_touches_security_dir(f) for f in files)


def is_exploratory(task: TaskDict) -> bool:
    """Check if task is exploratory (requires human reasoning)."""
    if task.get("task_type") == "research":
        return True
    title = (task.get("title") or "").lower()
    return any(kw in title for kw in EXPLORATORY_KEYWORDS)


def _classify_file_domain(path: str) -> str | None:
    """Return the domain name for a file path, or None if unclassified."""
    if path.startswith("backend/") or path.endswith(".py"):
        return "backend"
    if path.startswith("frontend/") or path.endswith((".tsx", ".ts", ".jsx", ".js")):
        return "frontend"
    if "migration" in path or path.endswith(".sql"):
        return "database"
    if path.startswith("infra/") or path.endswith((".yaml", ".yml", ".tf")):
        return "infra"
    return None


def count_domains(files: list[str]) -> int:
    """Count how many domains a task affects."""
    return len({_classify_file_domain(f) for f in files} - {None})


def _get_affected_files(task: TaskDict) -> list[str]:
    """Extract affected_files from task plan_content.context."""
    plan_content = task.get("plan_content") or {}
    context = plan_content.get("context") or {}
    return context.get("affected_files") or []


def check_exclusion(task: TaskDict) -> str | None:
    """Check if task should be excluded from autonomous execution.

    Returns:
        Exclusion reason string, or None if task is eligible.
    """
    labels = task.get("labels") or []
    affected_files = _get_affected_files(task)

    if "needs-tests" in labels:
        return "needs-tests label"
    if "needs-human-review" in labels:
        return "needs-human-review label"
    if is_standalone(task):
        return "standalone (no capability_id)"
    if has_standalone_label(task):
        return "standalone/exploratory label"
    if (task.get("tier") or 2) == 4:
        return "tier 4 (architecture)"
    if "architecture" in labels:
        return "architecture label"
    if affected_files and is_security_sensitive(affected_files):
        return "security-sensitive files"
    if is_exploratory(task):
        return "exploratory task"
    if affected_files and count_domains(affected_files) >= 3:
        return "multi-domain (3+ areas)"
    return None
