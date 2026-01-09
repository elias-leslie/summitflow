"""Agent Hub autocode service.

Dispatches coding tasks to AI workers and collects evidence contracts.
Uses Agent Hub orchestration API for subagent execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..constants import DEFAULT_CLAUDE_MODEL
from ..logging_config import get_logger
from .agent_hub_client import AgentHubLLMClient, LLMResponse

logger = get_logger(__name__)

AGENT_HUB_URL = os.getenv("AGENT_HUB_URL", "http://localhost:8003")
MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # Exponential backoff

EVIDENCE_SCHEMA_PATH = (
    Path(__file__).parent.parent.parent.parent / "tasks/autocode-orchestration/evidence-schema.json"
)
_evidence_schema: dict[str, Any] | None = None


def _load_evidence_schema() -> dict[str, Any]:
    """Load and cache the evidence schema."""
    global _evidence_schema
    if _evidence_schema is None:
        with open(EVIDENCE_SCHEMA_PATH) as f:
            _evidence_schema = json.load(f)
    assert _evidence_schema is not None
    return _evidence_schema


def validate_evidence(evidence_dict: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate evidence against the JSON schema.

    Args:
        evidence_dict: Evidence contract dictionary

    Returns:
        Tuple of (is_valid, error_message)
    """
    import jsonschema as js

    try:
        schema = _load_evidence_schema()
        js.validate(evidence_dict, schema)
        return True, None
    except js.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"
    except FileNotFoundError:
        logger.warning("evidence_schema_not_found", path=str(EVIDENCE_SCHEMA_PATH))
        return True, None  # Skip validation if schema not found
    except Exception as e:
        logger.error("evidence_validation_error", error=str(e))
        return False, f"Validation error: {e}"


@dataclass
class EvidenceContract:
    """Worker evidence contract matching evidence-schema.json."""

    task_id: str
    status: str  # completed, blocked, deferred, failed
    evidence: dict[str, Any]
    deferred_reason: str | None = None
    blocked_by: str | None = None
    error: str | None = None
    iterations: int = 1
    model_used: str = ""
    tokens_used: int = 0
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result: dict[str, Any] = {
            "task_id": self.task_id,
            "status": self.status,
            "evidence": self.evidence,
            "iterations": self.iterations,
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
        }
        if self.deferred_reason:
            result["deferred_reason"] = self.deferred_reason
        if self.blocked_by:
            result["blocked_by"] = self.blocked_by
        if self.error:
            result["error"] = self.error
        return result


@dataclass
class TaskContext:
    """Context for task dispatch to workers."""

    task_id: str
    subtask_id: str
    project_id: str
    description: str
    steps: list[dict[str, Any]]
    objective: str | None = None
    done_when: list[str] | None = None
    constraints: list[str] | None = None
    files_affected: list[str] = field(default_factory=list)
    repo_path: Path | None = None


@dataclass
class ExecutionState:
    """Tracks execution state for autocode operations."""

    execution_id: str
    task_id: str
    current_subtask_id: str | None = None
    status: str = "pending"  # pending, running, completed, failed
    evidence: EvidenceContract | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retries: int = 0


class AgentHubService:
    """Service for dispatching tasks to Agent Hub workers."""

    def __init__(
        self,
        project_id: str,
        model: str | None = None,
        repo_path: Path | None = None,
    ) -> None:
        self.project_id = project_id
        self.model = model or DEFAULT_CLAUDE_MODEL
        self.repo_path = repo_path or self._get_repo_path()
        self._client: AgentHubLLMClient | None = None
        self._executions: dict[str, ExecutionState] = {}

    def _get_repo_path(self) -> Path:
        """Get repository path for project."""
        from ..storage.projects import get_project_root_path

        path = get_project_root_path(self.project_id)
        if not path:
            raise ValueError(f"Project {self.project_id} not found or has no root_path")
        return Path(path)

    def _get_client(self) -> AgentHubLLMClient:
        """Get or create Agent Hub client."""
        if self._client is None:
            self._client = AgentHubLLMClient(
                model=self.model,
                base_url=AGENT_HUB_URL,
            )
        return self._client

    def dispatch_task(self, task_context: TaskContext) -> EvidenceContract:
        """Dispatch a task to a worker and collect evidence.

        Args:
            task_context: Context for task execution

        Returns:
            EvidenceContract with execution results

        Raises:
            RuntimeError: If execution fails after max retries
        """
        start_time = time.monotonic()
        total_tokens = 0
        iterations = 0
        last_error: str | None = None

        execution_id = f"exec-{task_context.subtask_id}-{int(datetime.now(UTC).timestamp())}"
        state = ExecutionState(
            execution_id=execution_id,
            task_id=task_context.task_id,
            current_subtask_id=task_context.subtask_id,
            status="running",
            started_at=datetime.now(UTC),
        )
        self._executions[execution_id] = state

        for attempt in range(MAX_RETRIES):
            iterations += 1
            state.retries = attempt

            try:
                response, evidence = self._execute_subtask(task_context)
                total_tokens += response.usage.get("total_tokens", 0)

                if evidence.status == "completed":
                    evidence.iterations = iterations
                    evidence.model_used = self.model
                    evidence.tokens_used = total_tokens
                    evidence.duration_ms = int((time.monotonic() - start_time) * 1000)

                    state.status = "completed"
                    state.evidence = evidence
                    state.completed_at = datetime.now(UTC)

                    logger.info(
                        "task_dispatch_success",
                        task_id=task_context.task_id,
                        subtask_id=task_context.subtask_id,
                        iterations=iterations,
                    )
                    return evidence

                last_error = evidence.error or "Worker did not complete successfully"

            except RuntimeError as e:
                last_error = f"Agent Hub error: {e}"
                logger.warning(
                    "task_dispatch_retry",
                    attempt=attempt + 1,
                    error=str(e),
                )
            except Exception as e:
                last_error = f"Execution error: {e}"
                logger.error(
                    "task_dispatch_error",
                    attempt=attempt + 1,
                    error=str(e),
                )

            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])

        state.status = "failed"
        state.completed_at = datetime.now(UTC)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        return EvidenceContract(
            task_id=task_context.subtask_id,
            status="failed",
            evidence={
                "files_modified": [],
                "commands_run": [],
                "verifications": [],
            },
            error=last_error or "Failed after max retries",
            iterations=iterations,
            model_used=self.model,
            tokens_used=total_tokens,
            duration_ms=duration_ms,
        )

    def _execute_subtask(
        self,
        task_context: TaskContext,
    ) -> tuple[LLMResponse, EvidenceContract]:
        """Execute a single subtask and return evidence.

        Returns:
            Tuple of (LLMResponse, EvidenceContract)
        """
        prompt = self._build_execution_prompt(task_context)
        client = self._get_client()

        system_prompt = self._build_system_prompt()

        response = client.generate(
            prompt=prompt,
            system=system_prompt,
            max_tokens=8192,
            temperature=0.7,
        )

        evidence = self._parse_and_execute(response.content, task_context)
        return response, evidence

    def _build_system_prompt(self) -> str:
        """Build system prompt for worker."""
        return """You are a coding worker executing a specific subtask. Your job is to:

1. Implement the required changes according to the task description and steps
2. Return your changes in a structured format
3. Verify your changes work

Output format - you MUST return a JSON evidence contract at the end of your response:

```json
{
  "status": "completed",
  "files": [
    {"path": "relative/path/to/file.py", "content": "full file content here"}
  ],
  "commands": [
    {"cmd": "pytest tests/test_file.py", "description": "run tests"}
  ],
  "verifications": [
    {"check": "file exists", "passed": true, "details": "verified file was created"}
  ]
}
```

If blocked, set status to "blocked" and include "blocked_by" with the blocking task ID.
If deferring, set status to "deferred" and include "deferred_reason" (min 10 chars).
If failed, set status to "failed" and include "error" message.

Focus on making minimal, correct changes. Do not over-engineer."""

    def _build_execution_prompt(self, context: TaskContext) -> str:
        """Build prompt for task execution."""
        steps_text = "\n".join(
            f"  {i + 1}. {step.get('description', step)}" for i, step in enumerate(context.steps)
        )

        prompt_parts = [
            f"# Task: {context.description}",
            "",
            f"Project: {context.project_id}",
            f"Subtask ID: {context.subtask_id}",
            "",
            "## Steps to complete:",
            steps_text,
        ]

        if context.objective:
            prompt_parts.extend(["", f"## Objective: {context.objective}"])

        if context.done_when:
            done_when_text = "\n".join(f"- {item}" for item in context.done_when)
            prompt_parts.extend(["", "## Done when:", done_when_text])

        if context.constraints:
            constraints_text = "\n".join(f"- {item}" for item in context.constraints)
            prompt_parts.extend(["", "## Constraints:", constraints_text])

        if context.files_affected:
            files_text = "\n".join(f"- {f}" for f in context.files_affected)
            prompt_parts.extend(["", "## Files to modify:", files_text])

        prompt_parts.extend(
            [
                "",
                "## Repository path:",
                str(context.repo_path or self.repo_path),
                "",
                "Implement the required changes and return your evidence contract.",
            ]
        )

        return "\n".join(prompt_parts)

    def _parse_and_execute(
        self,
        output: str,
        context: TaskContext,
    ) -> EvidenceContract:
        """Parse worker output and execute changes.

        Args:
            output: Raw LLM output
            context: Task context

        Returns:
            EvidenceContract with execution results
        """
        files_modified: list[str] = []
        commands_run: list[dict[str, Any]] = []
        verifications: list[dict[str, Any]] = []

        json_match = re.search(r"```json\s*\n(.*?)\n```", output, re.DOTALL)
        if not json_match:
            return EvidenceContract(
                task_id=context.subtask_id,
                status="failed",
                evidence={
                    "files_modified": [],
                    "commands_run": [],
                    "verifications": [],
                },
                error="No JSON evidence contract found in output",
            )

        try:
            worker_output = json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            return EvidenceContract(
                task_id=context.subtask_id,
                status="failed",
                evidence={
                    "files_modified": [],
                    "commands_run": [],
                    "verifications": [],
                },
                error=f"Invalid JSON in evidence contract: {e}",
            )

        status = worker_output.get("status", "failed")

        if status in ("blocked", "deferred", "failed"):
            return EvidenceContract(
                task_id=context.subtask_id,
                status=status,
                evidence={
                    "files_modified": [],
                    "commands_run": [],
                    "verifications": [],
                },
                blocked_by=worker_output.get("blocked_by"),
                deferred_reason=worker_output.get("deferred_reason"),
                error=worker_output.get("error"),
            )

        repo_path = context.repo_path or self.repo_path

        for file_change in worker_output.get("files", []):
            path = file_change.get("path")
            content = file_change.get("content")
            if path and content:
                full_path = repo_path / path
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(content)
                    files_modified.append(path)
                    logger.debug("file_written", path=path)
                except Exception as e:
                    logger.error("file_write_failed", path=path, error=str(e))
                    verifications.append(
                        {
                            "check": f"write {path}",
                            "passed": False,
                            "details": str(e),
                        }
                    )

        for cmd_spec in worker_output.get("commands", []):
            cmd = cmd_spec.get("cmd")
            if cmd:
                cmd_result = self._run_command(cmd, repo_path)
                commands_run.append(cmd_result)
                verifications.append(
                    {
                        "check": cmd_spec.get("description", cmd),
                        "passed": cmd_result["exit_code"] == 0,
                        "details": f"exit code: {cmd_result['exit_code']}",
                    }
                )

        git_diff_hash = self._compute_git_diff_hash(repo_path)

        for v in worker_output.get("verifications", []):
            verifications.append(
                {
                    "check": v.get("check", "unknown"),
                    "passed": v.get("passed", False),
                    "details": v.get("details"),
                }
            )

        return EvidenceContract(
            task_id=context.subtask_id,
            status="completed" if files_modified else "failed",
            evidence={
                "files_modified": files_modified,
                "commands_run": commands_run,
                "verifications": verifications,
                "git_diff_hash": git_diff_hash,
            },
            error=None if files_modified else "No files were modified",
        )

    def _run_command(self, cmd: str, cwd: Path) -> dict[str, Any]:
        """Run a command and capture output."""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {
                "cmd": cmd,
                "exit_code": result.returncode,
                "stdout_hash": hashlib.sha256(result.stdout.encode()).hexdigest(),
                "stderr_hash": hashlib.sha256(result.stderr.encode()).hexdigest(),
            }
        except subprocess.TimeoutExpired:
            return {
                "cmd": cmd,
                "exit_code": -1,
                "stdout_hash": "",
                "stderr_hash": hashlib.sha256(b"timeout").hexdigest(),
            }
        except Exception as e:
            return {
                "cmd": cmd,
                "exit_code": -1,
                "stdout_hash": "",
                "stderr_hash": hashlib.sha256(str(e).encode()).hexdigest(),
            }

    def _compute_git_diff_hash(self, repo_path: Path) -> str:
        """Compute SHA256 hash of git diff."""
        try:
            result = subprocess.run(
                ["git", "diff"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return hashlib.sha256(result.stdout.encode()).hexdigest()
        except Exception:
            return ""

    def get_execution_state(self, execution_id: str) -> ExecutionState | None:
        """Get current execution state."""
        return self._executions.get(execution_id)

    def list_executions(self, task_id: str | None = None) -> list[ExecutionState]:
        """List all executions, optionally filtered by task."""
        executions = list(self._executions.values())
        if task_id:
            executions = [e for e in executions if e.task_id == task_id]
        return executions

    def close(self) -> None:
        """Close client connections."""
        if self._client:
            self._client.close()
            self._client = None


def dispatch_task(
    project_id: str,
    task_context: TaskContext,
    model: str | None = None,
) -> EvidenceContract:
    """Dispatch a task to Agent Hub worker.

    Convenience function for one-off task dispatch.

    Args:
        project_id: Project ID
        task_context: Task context for execution
        model: Optional model override

    Returns:
        EvidenceContract with execution results
    """
    service = AgentHubService(project_id, model=model)
    try:
        return service.dispatch_task(task_context)
    finally:
        service.close()
