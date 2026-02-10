"""Task eligibility and exclusion filters for autonomous execution."""

from __future__ import annotations

import re
from typing import Any

# Validation mode flags - disabled after phase 5 validation
# Re-enable for debugging or controlled testing
AUTONOMOUS_DRY_RUN = False  # When True, log what would execute but don't actually run
VALIDATION_MODE = False  # When True, only execute tasks in ALLOWED_TASK_IDS
ALLOWED_TASK_IDS: list[str] = []  # Empty = no filter (when VALIDATION_MODE=True)

# Patterns in error titles that should NOT generate bug tasks
# These are environmental/transient issues, not actual code bugs
ERROR_BLOCKLIST_PATTERNS = [
    # Database connection issues (environmental, not bugs)
    "postgresql",
    "role.*does not exist",
    "database.*role",
    "authentication failure",
    "connection failed",
    "psql",
    # Pre-existing type errors (not new bugs, need consolidated approach)
    "mypy",
    "type error",
    "type mismatch",
    "type check",
    # TypeScript transient issues
    "typescript.*not found",
    "ts2307",
    "ts6053",
    "tsc",
    "module resolution",
    # Missing tools/dependencies (environmental)
    "missing from path",
    "cli missing",
    "command not found",
    "dependency",
    "package.json",
    # Transient test/build failures
    "file not found",
    "test file",
    "migration inspection",
    "jq filter",
    "jq syntax",
    # Test infrastructure patterns
    "capability verification",
]

# Security-sensitive directory names that require human review
SECURITY_DIRS = ["auth", "security", "payment", "credentials", "secret", "crypto", "oauth"]

# Exploratory task indicators
EXPLORATORY_KEYWORDS = ["investigate", "explore", "understand", "research", "analyze"]

# Standalone task labels that require manual execution
STANDALONE_LABELS = ["standalone", "exploratory"]


def is_blocklisted_error(title: str) -> bool:
    """Check if error title matches blocklist patterns.

    These are environmental/transient issues that should NOT create tasks.
    """
    title_lower = title.lower()
    return any(re.search(pattern, title_lower) for pattern in ERROR_BLOCKLIST_PATTERNS)


def is_standalone(task: dict[str, Any]) -> bool:
    """Check if task is standalone (no capability linkage).

    Standalone tasks require manual execution because they lack
    capability-driven acceptance criteria for autonomous verification.

    Exception: auto-generated tasks and autonomous task types (refactor, debt, regression)
    have subtasks+steps which can be verified without capability linkage.
    """
    # Autonomous task types have subtask verification
    task_type = task.get("task_type", "task")
    if task_type in ("refactor", "debt", "regression"):
        return False

    # Auto-generated label also indicates subtask verification
    labels = task.get("labels") or []
    if "auto-generated" in labels:
        return False

    return task.get("capability_id") is None


def has_standalone_label(task: dict[str, Any]) -> bool:
    """Check if task has a standalone or exploratory label."""
    labels = task.get("labels") or []
    return any(label in STANDALONE_LABELS for label in labels)


def is_security_sensitive(files: list[str]) -> bool:
    """Check if any files are in security-sensitive directories."""
    for f in files:
        parts = f.lower().split("/")
        for part in parts:
            if any(sec in part for sec in SECURITY_DIRS):
                return True
    return False


def is_exploratory(task: dict[str, Any]) -> bool:
    """Check if task is exploratory (requires human reasoning)."""
    task_type = task.get("task_type", "")
    if task_type == "research":
        return True
    title = (task.get("title") or "").lower()
    return any(kw in title for kw in EXPLORATORY_KEYWORDS)


def count_domains(files: list[str]) -> int:
    """Count how many domains a task affects."""
    domains = set()
    for f in files:
        if f.startswith("backend/") or f.endswith(".py"):
            domains.add("backend")
        elif f.startswith("frontend/") or f.endswith((".tsx", ".ts", ".jsx", ".js")):
            domains.add("frontend")
        elif "migration" in f or f.endswith(".sql"):
            domains.add("database")
        elif f.startswith("infra/") or f.endswith((".yaml", ".yml", ".tf")):
            domains.add("infra")
    return len(domains)


def check_exclusion(task: dict[str, Any]) -> str | None:
    """Check if task should be excluded from autonomous execution.

    Returns:
        Exclusion reason string, or None if task is eligible
    """
    labels = task.get("labels") or []
    tier = task.get("tier") or 2

    # Get affected files from plan_content or description
    plan_content = task.get("plan_content") or {}
    context = plan_content.get("context") or {}
    affected_files = context.get("affected_files") or []

    # EXCLUDE: labels contain 'needs-tests' or 'needs-human-review'
    if "needs-tests" in labels:
        return "needs-tests label"
    if "needs-human-review" in labels:
        return "needs-human-review label"

    # EXCLUDE: standalone tasks (no capability_id) - require manual execution
    if is_standalone(task):
        return "standalone (no capability_id)"

    # EXCLUDE: 'standalone' or 'exploratory' labels
    if has_standalone_label(task):
        return "standalone/exploratory label"

    # EXCLUDE: tier=4 OR labels contain 'architecture' (architectural)
    if tier == 4:
        return "tier 4 (architecture)"
    if "architecture" in labels:
        return "architecture label"

    # EXCLUDE: files match security patterns
    if affected_files and is_security_sensitive(affected_files):
        return "security-sensitive files"

    # EXCLUDE: task_type='research' OR title matches explore keywords
    if is_exploratory(task):
        return "exploratory task"

    # EXCLUDE: affects 3+ domains (multi_domain)
    if affected_files and count_domains(affected_files) >= 3:
        return "multi-domain (3+ areas)"

    return None  # No exclusion - task is eligible
