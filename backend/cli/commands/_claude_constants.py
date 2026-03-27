"""Constants and data types for the Claude worker dispatch commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

_AGENT_HUB_PROJECT_ID = "agent-hub"
_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_TIMEOUT_SECONDS = 1800
_DEFAULT_SOURCE = "st-cli"
_DEFAULT_MAX_SUBAGENTS = 4
_ORCHESTRATOR_SOURCE = "st-cli-orchestrator"
_ORCHESTRATOR_ALLOWED_TOOLS = "Read,Agent,Edit,MultiEdit,Write,Bash,Glob,Grep,LS"
_BACKEND_SUBDIR = "backend"
_TASK_STATUS_RUNNING = "running"
_WORKER_SUBAGENT_NAME = "task-worker"
_WORKER_SUBAGENT_MODEL = "sonnet"
_COMMIT_SCRIPT = "commit.sh"
_WORKTREE_PATH_PREFIX = "WORKTREE_PATH:"
_ORCHESTRATE_TMPDIR_PREFIX = "st-claude-orchestrate-"
_ORCHESTRATOR_PROMPT_FNAME = "orchestrator_prompt.md"
_ORCHESTRATOR_AGENTS_FNAME = "orchestrator_agents.json"

_WORKER_SUBAGENT_PAYLOAD: dict[str, Any] = {
    _WORKER_SUBAGENT_NAME: {
        "description": "Lane-bound task implementation worker",
        "prompt": (
            "You are assigned exactly one SummitFlow task lane. Work only inside the provided "
            "task worktree and only on files required for that task. Preserve behavior unless "
            "the task explicitly changes it. Run task-appropriate verification and `dt --quick "
            "--changed-only` before reporting success. If everything passes, run "
            '`commit.sh --current --push --task <task-id> --msg "..."` from the assigned '
            "worktree. Do not run `st done`; report back to the orchestrator."
        ),
        "tools": ["Read", "Edit", "MultiEdit", "Write", "Bash", "Glob", "Grep", "LS"],
        "model": _WORKER_SUBAGENT_MODEL,
    }
}


@dataclass(frozen=True)
class WorkerDispatch:
    index: int
    task_id: str
    project_id: str
    project_root: Path
    command: list[str]
    cwd: Path


@dataclass(frozen=True)
class OrchestratorTask:
    index: int
    task_id: str
    project_id: str
    project_root: Path
    worktree_path: Path
    context_text: str
