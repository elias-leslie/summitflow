"""Autonomous task execution with self-healing and quality gates.

This package contains the refactored execution logic split across focused modules:

- orchestrator: Main task execution flow
- subtask_executor: Subtask execution with self-healing retry loop
- quality: Pristine checking and quality gates
- steps: Step verification and utilities
- prompts: Prompt template management
- events: Event emission for timeline tracking
- git_ops: Git operations (commit, status)
- worktree: Worktree health checking
- agent_routing: Agent selection and supervisor utilities
- session: Handoff and wind-down session management
"""

from .orchestrator import start_execution

__all__ = ["start_execution"]
