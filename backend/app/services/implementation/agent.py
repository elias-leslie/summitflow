"""Implementation agent - Agent execution and model consultation.

Handles interaction with AI agents (Claude, Gemini) for code generation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...constants import DEFAULT_GEMINI_MODEL
from ...logging_config import get_logger
from ..agent_hub_client import get_agent

logger = get_logger(__name__)


def execute_agent(
    model: dict[str, Any],
    prompt: str,
    working_dir: Path | None = None,
) -> str:
    """Execute agent with model and prompt.

    Args:
        model: ModelConfig dict with provider, model, description
        prompt: The execution prompt built by prompt_builder
        working_dir: Working directory for file operations (Claude only)

    Returns:
        Agent response text (should contain ```file:path``` blocks)
    """
    provider = model.get("provider", "gemini")
    model_id = model.get("model", DEFAULT_GEMINI_MODEL)

    logger.info(
        "agent_execution_start",
        provider=provider,
        model=model_id,
        prompt_len=len(prompt),
    )

    try:
        agent = get_agent("coder")

        # Use working_dir for Claude to enable file operations
        working_dir_str = str(working_dir) if provider == "claude" and working_dir else None

        response = agent.generate(
            prompt=prompt,
            system="You are an expert software engineer implementing code changes. Output only valid code changes in the specified format.",
            temperature=0.7,
            working_dir=working_dir_str,
        )

        logger.info(
            "agent_execution_complete",
            provider=provider,
            model=model_id,
            response_len=len(response.content),
            tokens_used=response.usage.get("total_tokens", 0) if response.usage else 0,
        )

        return response.content

    except Exception as e:
        logger.error(
            "agent_execution_failed",
            provider=provider,
            model=model_id,
            error=str(e),
        )
        raise


def consult_alternate(
    model: dict[str, Any],
    task: dict[str, Any],
    error: str,
) -> str:
    """Consult alternate model for advice on fixing errors.

    When the primary model is thrashing (hitting same error repeatedly),
    we ask a different model for fresh perspective.

    Args:
        model: Current model config (we'll use the opposite provider)
        task: Task dict with title, description
        error: The repeated error message

    Returns:
        Advice string from alternate model
    """
    # Always use analyst agent for consultation (routes to appropriate model)
    alt_provider = "analyst"

    logger.info(
        "consulting_alternate",
        primary_provider=model.get("provider", "claude"),
        alt_provider=alt_provider,
        error_len=len(error),
    )

    try:
        agent = get_agent("analyst")

        prompt = f"""A code implementation task is failing repeatedly with the same error.

Task: {task.get("title", "Unknown task")}
Description: {task.get("description", "No description")}

Repeated Error:
{error[:2000]}

Please analyze this error and provide specific, actionable advice to fix it.
Focus on:
1. Root cause of the error
2. Concrete steps to fix it
3. Any edge cases to consider

Keep response concise (under 500 words)."""

        response = agent.generate(
            prompt=prompt,
            system="You are a debugging expert. Provide clear, actionable advice.",
            temperature=0.3,
        )

        logger.info(
            "alternate_consultation_complete",
            alt_provider=alt_provider,
            response_len=len(response.content),
        )

        return response.content

    except Exception as e:
        logger.warning(
            "alternate_consultation_failed",
            error=str(e),
        )
        return f"Consultation failed: {e}. Consider reviewing the error manually."


def parse_and_apply_changes(output: str, repo_path: Path, use_worktree: bool = False) -> bool:
    """Parse agent output and apply file changes.

    Expected format:
    ```file:path/to/file.py
    file contents
    ```

    Args:
        output: Agent output text
        repo_path: Path to repository (main or worktree)
        use_worktree: Whether we're operating in a worktree

    Returns:
        True if changes were applied, False otherwise
    """
    pattern = r"```file:([^\n]+)\n(.*?)```"
    matches = re.findall(pattern, output, re.DOTALL)

    if not matches:
        return False

    for file_path, content in matches:
        file_path = file_path.strip()
        full_path = repo_path / file_path

        # Create parent directories if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        full_path.write_text(content.strip() + "\n")
        logger.info("file_written", path=file_path, in_worktree=use_worktree)

    return True
