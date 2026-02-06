"""Fix execution utilities for fix agent.

Handles file I/O and verification of fixes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...logging_config import get_logger
from ...services.agent_hub_client import get_agent
from .cost_estimator import estimate_cost_from_response

logger = get_logger(__name__)


def read_file_content(file_path: Path) -> str | None:
    """Read file content."""
    if not file_path.exists():
        return None
    try:
        return file_path.read_text()
    except Exception as e:
        logger.warning("read_file_failed", path=str(file_path), error=str(e))
        return None


def apply_fix(file_path: Path, new_content: str) -> bool:
    """Apply the fix to the file."""
    try:
        file_path.write_text(new_content)
        return True
    except Exception as e:
        logger.error("apply_fix_failed", path=str(file_path), error=str(e))
        return False


def verify_fix(
    project_path: Path,
    check_type: str,
    file_path: str,
) -> bool:
    """Re-run the check to verify the fix worked."""
    cmd_map = {
        "ruff": ["ruff", "check", file_path, "--quiet"],
        "mypy": ["mypy", file_path, "--no-error-summary", "--quiet"],
        "biome": ["npx", "biome", "check", file_path, "--quiet"],
        "tsc": ["npx", "tsc", "--noEmit"],
    }
    cmd = cmd_map.get(check_type)
    if not cmd:
        logger.warning("unknown_check_type", check_type=check_type)
        return False

    try:
        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0
    except Exception as e:
        logger.error("verify_failed", check_type=check_type, error=str(e))
        return False


def execute_agent_fix(
    agent_slug: str,
    prompt: str,
    temperature: float,
) -> tuple[str, float]:
    """Execute fix using specified agent and return content + cost."""
    agent = get_agent(agent_slug)
    response = agent.generate(
        prompt=prompt,
        system="You are a code fix agent. Output only the fixed code, no explanations.",
        temperature=temperature,
        purpose="quality_gate_fix",
    )
    return response.content.strip(), estimate_cost_from_response(response)
