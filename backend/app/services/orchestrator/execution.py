"""Subtask execution logic for orchestrator.

Handles dispatching work to agent workers and analyzing results.
"""

from __future__ import annotations

from pathlib import Path

from ...logging_config import get_logger

logger = get_logger(__name__)


def build_prompt(
    subtask: dict[str, object],
    effective_repo_path: Path,
    chat_messages: list[dict[str, object]],
) -> str:
    """Build prompt for worker with task context and user directions.

    Args:
        subtask: Subtask to execute
        effective_repo_path: Working directory path
        chat_messages: User chat messages for context

    Returns:
        Formatted prompt string
    """
    subtask_id = subtask.get("subtask_full_id") or subtask.get("id")
    description = subtask.get("description", "")
    steps = subtask.get("steps", [])

    if not isinstance(steps, list):
        steps = []
    steps_text = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))

    user_directions = ""
    if chat_messages:
        recent_messages = chat_messages[-3:]
        directions = [f"- {m.get('content', '')}" for m in recent_messages if m.get("content")]
        if directions:
            user_directions = f"""
## User Directions
The user has provided the following guidance:
{chr(10).join(directions)}

Please incorporate this direction into your work.
"""

    prompt = f"""# Task: Execute Subtask {subtask_id}

## Description
{description}

## Steps to Complete
{steps_text}

## Working Directory
{effective_repo_path}
{user_directions}
## Instructions
You are an expert software engineer. Complete the steps above.
For each step:
1. Read relevant files to understand the codebase
2. Make necessary code changes
3. Verify your changes work

After completing all steps, respond with:
- DONE: If all steps completed successfully
- BLOCKED: <reason> if you cannot proceed
- ERROR: <details> if an error occurred

Be concise in your responses. Focus on completing the task."""

    return prompt


def analyze_execution_result(content: str, subtask: dict[str, object]) -> tuple[bool, str | None]:
    """Analyze agent response to determine success/failure.

    Args:
        content: Agent response content
        subtask: The subtask that was executed

    Returns:
        Tuple of (success, error_message)
    """
    content_lower = content.lower()

    if "done:" in content_lower or "completed successfully" in content_lower:
        return True, None

    if "blocked:" in content_lower:
        idx = content_lower.find("blocked:")
        reason = content[idx + 8 :].strip()[:200]
        return False, f"Blocked: {reason}"

    if "error:" in content_lower:
        idx = content_lower.find("error:")
        error = content[idx + 6 :].strip()[:200]
        return False, f"Error: {error}"

    failure_patterns = [
        "cannot complete",
        "unable to",
        "failed to",
        "i cannot",
        "not possible",
    ]
    for pattern in failure_patterns:
        if pattern in content_lower:
            return False, f"Agent reported inability: {pattern}"

    if len(content) > 100:
        return True, None

    return False, "Inconclusive response from agent"


async def dispatch_to_worker(
    subtask: dict[str, object],
    model: str,
    effective_repo_path: Path,
    chat_messages: list[dict[str, object]],
    send_log: object,
) -> tuple[bool, str | None]:
    """Dispatch subtask to worker agent for execution.

    Uses Agent Hub SDK's run_agent for agentic execution with tool calling.

    Args:
        subtask: Subtask to execute
        model: Agent/model to use
        effective_repo_path: Working directory path
        chat_messages: User chat messages for context
        send_log: Async function to send log messages

    Returns:
        Tuple of (success, error_message)
    """
    from ..agent_hub_client import get_async_client

    subtask_id = str(subtask.get("subtask_full_id") or subtask.get("id") or "unknown")
    description = subtask.get("description", "")

    logger.info(
        "dispatch_to_worker",
        subtask_id=subtask_id,
        model=model,
        description=str(description)[:50],
    )

    prompt = build_prompt(subtask, effective_repo_path, chat_messages)
    provider = "claude" if "claude" in model.lower() else "gemini"

    async def _log(level: str, message: str, source: str = "orchestrator") -> None:
        if callable(send_log):
            await send_log(level, message, source)

    await _log("info", f"Starting agent execution with {provider}/{model}")

    try:
        async with get_async_client() as client:
            result = await client.run_agent(
                task=prompt,
                provider=provider,
                model=model,
                system_prompt="You are an expert software engineer executing tasks. Be thorough and precise.",
                max_turns=20,
                enable_code_execution=(provider == "claude"),
                working_dir=str(effective_repo_path),
                timeout_seconds=300.0,
            )

            for progress in result.progress_log:
                if progress.status == "running":
                    await _log(
                        "info", f"Turn {progress.turn}: {progress.message}", source="worker"
                    )
                elif progress.status == "tool_use":
                    tool_names = [tc.get("name", "?") for tc in progress.tool_calls]
                    await _log(
                        "info", f"Tool calls: {', '.join(tool_names)}", source="worker"
                    )
                elif progress.status == "complete":
                    await _log(
                        "info",
                        f"Agent completed: {result.input_tokens} in, {result.output_tokens} out",
                        source="worker",
                    )

            if result.status == "error":
                await _log("error", f"Agent error: {result.error}")
                return False, result.error

            if result.status == "max_turns":
                await _log("warning", "Agent reached max turns")

            success, error = analyze_execution_result(result.content, subtask)
            return success, error

    except Exception as e:
        logger.error("dispatch_to_worker_error", subtask_id=subtask_id, error=str(e))
        await _log("error", f"Execution failed: {e}")
        return False, str(e)


def requires_human_review(task: dict[str, object]) -> bool:
    """Check if task requires human review based on complexity heuristics.

    Args:
        task: Task dict

    Returns:
        True if task should be routed to human review
    """
    labels = task.get("labels", [])
    if not isinstance(labels, list):
        labels = []

    security_patterns = ["security", "auth", "credential", "payment", "crypto"]
    if any(pattern in str(label).lower() for label in labels for pattern in security_patterns):
        return True

    domain_labels = [label for label in labels if str(label).startswith("domains:")]
    if len(domain_labels) >= 3:
        return True

    if "needs-human-review" in labels:
        return True

    return "architecture" in labels or "breaking-change" in labels
