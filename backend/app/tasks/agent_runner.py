"""Celery tasks for agent execution.

Tasks:
- run_agent_task: Execute an agent on a specific task
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.agents import AgentType, get_agent
from ..storage import capabilities, tasks, tests

logger = get_logger(__name__)


# TDD Build mode system prompt
TDD_SYSTEM_PROMPT = """You are an AI development assistant implementing features using Test-Driven Development (TDD).

Your role is to:
1. Analyze the failing tests and understand why they fail
2. Implement the minimal code changes needed to make tests pass
3. Suggest file modifications with clear diffs
4. Focus on passing the specific tests, not over-engineering

When responding:
- Start with a brief analysis of the test failure
- List the files that need to be modified
- Provide the exact code changes needed
- Be specific about file paths and line numbers when possible

Format code changes as:
```python
# File: path/to/file.py
<code changes>
```"""


@shared_task(
    name="summitflow.run_agent_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=270,  # 4.5 minutes soft limit
    time_limit=300,  # 5 minutes hard limit
)
def run_agent_task(
    self,
    task_id: str,
    agent_type: AgentType,
    model: str | None = None,
) -> dict[str, Any]:
    """Execute an agent on a specific task.

    This is the main entry point for running an agent to work on a feature.
    The agent is initialized with the feature context and executes to
    implement the acceptance criteria.

    Args:
        self: Celery task instance (for retry support)
        task_id: The task ID to execute
        agent_type: Either "claude" or "gemini"
        model: Optional model override

    Returns:
        Summary dict with status, tokens_used, and completion info
    """
    logger.info(
        "agent_task_started",
        task_id=task_id,
        agent_type=agent_type,
        model=model,
    )

    # 1. Load task from database
    task = tasks.get_task(task_id)
    if not task:
        logger.error("task_not_found", task_id=task_id)
        return {"status": "error", "error": f"Task not found: {task_id}"}

    project_id = task["project_id"]
    capability_db_id = task.get("capability_id")

    # 2. Update task status to running
    tasks.update_task_status(task_id, "running")
    tasks.append_progress_log(task_id, f"Starting agent execution with {agent_type}")

    try:
        # 3. Load capability if linked (TDD architecture)
        capability = None
        cap_tests = []
        if capability_db_id:
            capability = capabilities.get_capability_by_id(capability_db_id)
            if capability:
                cap_tests = tests.get_tests_for_capability(project_id, capability["id"])
                tasks.append_progress_log(
                    task_id,
                    f"Loaded capability: {capability['name']} with {len(cap_tests)} tests",
                )

        # 4. Initialize agent
        try:
            agent = get_agent(agent_type, model)
            if not agent.is_available():
                raise RuntimeError(f"{agent_type} agent is not available")
            tasks.append_progress_log(
                task_id, f"Initialized {agent_type} agent ({agent.get_model_name()})"
            )
        except Exception as e:
            logger.error("agent_init_failed", agent_type=agent_type, error=str(e))
            tasks.update_task_status(task_id, "failed", error_message=str(e))
            tasks.append_progress_log(task_id, f"ERROR: Failed to initialize agent: {e}")
            return {"status": "error", "error": f"Agent init failed: {e}"}

        # 5. Build context prompt
        context = _build_agent_context(task, capability, cap_tests)
        tasks.append_progress_log(task_id, "Built capability context for agent")

        # 6. Execute agent
        tasks.append_progress_log(task_id, "Sending prompt to agent...")

        try:
            response = agent.generate(
                prompt=context,
                system=_get_system_prompt(project_id),
                max_tokens=4096,
            )
            # Support both naming conventions (Claude uses input_tokens, Gemini uses prompt_tokens)
            input_tokens = response.usage.get("input_tokens") or response.usage.get(
                "prompt_tokens", 0
            )
            output_tokens = response.usage.get("output_tokens") or response.usage.get(
                "completion_tokens", 0
            )
            tasks.append_progress_log(
                task_id,
                f"Agent response received ({input_tokens} in, {output_tokens} out)",
            )
        except Exception as e:
            logger.error("agent_execution_failed", task_id=task_id, error=str(e))
            # Retry on transient failures
            try:
                raise self.retry(exc=e)
            except self.MaxRetriesExceededError:
                tasks.update_task_status(
                    task_id, "failed", error_message=f"Agent execution failed: {e}"
                )
                tasks.append_progress_log(task_id, f"ERROR: Agent failed after retries: {e}")
                return {"status": "error", "error": str(e)}

        # 7. Update task with results
        total_tokens = input_tokens + output_tokens
        tasks.update_task(
            task_id,
            total_tokens_used=(task.get("total_tokens_used") or 0) + total_tokens,
            total_sessions=(task.get("total_sessions") or 0) + 1,
        )

        # 8. Log agent output
        # Truncate very long outputs for the log
        output_preview = (
            response.content[:500] + "..." if len(response.content) > 500 else response.content
        )
        tasks.append_progress_log(task_id, f"Agent output:\n{output_preview}")

        # 9. Mark task as completed (for now - Phase 6 will add criterion-by-criterion)
        tasks.update_task_status(task_id, "completed")
        tasks.append_progress_log(task_id, "Task completed successfully")

        logger.info(
            "agent_task_completed",
            task_id=task_id,
            tokens_used=total_tokens,
        )

        return {
            "status": "success",
            "task_id": task_id,
            "tokens_used": total_tokens,
            "output_length": len(response.content),
            "agent": agent_type,
            "model": agent.get_model_name(),
        }

    except Exception as e:
        logger.error("agent_task_unexpected_error", task_id=task_id, error=str(e))
        tasks.update_task_status(task_id, "failed", error_message=str(e))
        tasks.append_progress_log(task_id, f"ERROR: Unexpected error: {e}")
        return {"status": "error", "error": str(e)}


def _build_agent_context(
    task: dict[str, Any],
    capability: dict[str, Any] | None,
    cap_tests: list[dict[str, Any]],
) -> str:
    """Build the context prompt for the agent.

    Args:
        task: Task dict from database
        capability: Capability dict (optional)
        cap_tests: List of tests linked to capability

    Returns:
        Formatted context string for the agent
    """
    parts = [f"# Task: {task['title']}"]

    if task.get("description"):
        parts.append(f"\n## Description\n{task['description']}")

    if capability:
        parts.append(f"\n## Capability: {capability['name']}")
        if capability.get("description"):
            parts.append(f"\n{capability['description']}")
        parts.append(f"\n**Priority:** P{capability.get('priority', 2)}")
        parts.append(f"**Status:** {capability.get('status', 'pending')}")

    if cap_tests:
        parts.append("\n## Tests")
        for i, test in enumerate(cap_tests, 1):
            status = "PASS" if test.get("passes") else "PENDING"
            parts.append(f"\n{i}. [{status}] {test['name']}")
            if test.get("test_type"):
                parts.append(f"   Type: {test['test_type']}")

    if task.get("spec_content"):
        parts.append(f"\n## Specification\n{task['spec_content']}")

    if task.get("plan_content"):
        import json

        plan = task["plan_content"]
        if isinstance(plan, str):
            plan = json.loads(plan)
        parts.append(f"\n## Plan\n{json.dumps(plan, indent=2)}")

    parts.append(
        "\n## Instructions\n"
        "Analyze the feature and acceptance criteria above. "
        "For each pending criterion, outline the steps needed to implement it. "
        "Focus on concrete, actionable implementation details."
    )

    return "\n".join(parts)


def _get_system_prompt(project_id: str) -> str:
    """Get the system prompt for the agent.

    Args:
        project_id: Project ID for context

    Returns:
        System prompt string
    """
    return f"""You are an AI development assistant working on project '{project_id}'.

Your role is to help implement features by:
1. Analyzing requirements and acceptance criteria
2. Proposing concrete implementation steps
3. Identifying potential issues or blockers
4. Suggesting file changes needed

Be specific and actionable. Reference exact file paths and code locations where possible.
Format your response clearly with sections for each criterion you're addressing."""


@shared_task(
    name="summitflow.run_agent_tdd",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    soft_time_limit=270,
    time_limit=300,
)
def run_agent_tdd(
    self,
    project_id: str,
    capability_id: str,
    test_results: list[dict[str, Any]],
    agent_type: AgentType = "claude",
    model: str | None = None,
) -> dict[str, Any]:
    """Execute an agent in TDD mode to fix failing tests.

    This is called by the build orchestrator when tests fail for a capability.
    The agent receives the test failure context and suggests code fixes.

    Args:
        self: Celery task instance
        project_id: Project ID
        capability_id: Capability being built
        test_results: List of test results with failure info
        agent_type: Agent to use
        model: Optional model override

    Returns:
        Dict with suggested fixes and implementation steps
    """
    logger.info(
        "agent_tdd_started",
        project_id=project_id,
        capability_id=capability_id,
        agent_type=agent_type,
    )

    # 1. Load capability
    capability = capabilities.get_capability(project_id, capability_id)
    if not capability:
        logger.error("capability_not_found", capability_id=capability_id)
        return {"status": "error", "error": f"Capability not found: {capability_id}"}

    # 2. Load linked tests
    cap_tests = tests.get_tests_for_capability(project_id, capability["id"])

    try:
        # 3. Initialize agent
        try:
            agent = get_agent(agent_type, model)
            if not agent.is_available():
                raise RuntimeError(f"{agent_type} agent is not available")
        except Exception as e:
            logger.error("agent_init_failed", agent_type=agent_type, error=str(e))
            return {"status": "error", "error": f"Agent init failed: {e}"}

        # 4. Build TDD context prompt
        context = _build_tdd_context(capability, cap_tests, test_results)

        # 5. Execute agent
        try:
            response = agent.generate(
                prompt=context,
                system=TDD_SYSTEM_PROMPT,
                max_tokens=8192,  # More tokens for code changes
            )
            input_tokens = response.usage.get("input_tokens") or response.usage.get(
                "prompt_tokens", 0
            )
            output_tokens = response.usage.get("output_tokens") or response.usage.get(
                "completion_tokens", 0
            )
        except Exception as e:
            logger.error("agent_tdd_execution_failed", error=str(e))
            try:
                raise self.retry(exc=e)
            except self.MaxRetriesExceededError:
                return {"status": "error", "error": str(e)}

        logger.info(
            "agent_tdd_completed",
            project_id=project_id,
            capability_id=capability_id,
            tokens_used=input_tokens + output_tokens,
        )

        return {
            "status": "success",
            "capability_id": capability_id,
            "response": response.content,
            "tokens_used": input_tokens + output_tokens,
            "agent": agent_type,
            "model": agent.get_model_name(),
        }

    except Exception as e:
        logger.error("agent_tdd_unexpected_error", error=str(e))
        return {"status": "error", "error": str(e)}


def _build_tdd_context(
    capability: dict[str, Any],
    cap_tests: list[dict[str, Any]],
    test_results: list[dict[str, Any]],
) -> str:
    """Build TDD context prompt with test failure info.

    Args:
        capability: Capability dict
        cap_tests: Tests linked to this capability
        test_results: Actual test execution results

    Returns:
        Formatted context for TDD agent
    """
    parts = [f"# Capability: {capability['name']}"]

    if capability.get("description"):
        parts.append(f"\n{capability['description']}")

    parts.append(f"\nPriority: P{capability.get('priority', 2)}")
    parts.append(f"Status: {capability.get('status', 'pending')}")

    # List tests
    parts.append("\n## Tests for this capability")
    for test in cap_tests:
        parts.append(f"\n### {test['name']}")
        parts.append(f"Type: {test['test_type']}")
        if test.get("command"):
            parts.append(f"Command: `{test['command']}`")

    # Show failures
    failed_results = [r for r in test_results if not r.get("passed", False)]
    if failed_results:
        parts.append("\n## Failing Tests")
        for result in failed_results:
            parts.append("\n### Test Failure")
            if result.get("output"):
                # Truncate very long output
                output = (
                    result["output"][:1500]
                    if len(result.get("output", "")) > 1500
                    else result["output"]
                )
                parts.append(f"\n```\n{output}\n```")
            if result.get("error"):
                parts.append(f"\nError: {result['error']}")

    parts.append(
        "\n## Instructions\n"
        "Analyze the failing tests above. Identify the root cause and provide "
        "the minimal code changes needed to make them pass.\n\n"
        "Respond with:\n"
        "1. Brief analysis of why tests are failing\n"
        "2. File-by-file code changes needed\n"
        "3. Verification steps after implementation"
    )

    return "\n".join(parts)
