"""Fix strategy selection and prompt enhancement.

Handles agent selection based on escalation level and prompt enhancement
for supervisor-level attempts.
"""

from __future__ import annotations

SUPERVISOR_ENHANCEMENT = """Previous fix attempts have failed. Try a different approach.

{base_prompt}

IMPORTANT: Previous attempts failed. Consider:
- Reading surrounding context more carefully
- The error might require structural changes, not just line fixes
- Check if imports or dependencies are missing
- Verify the fix actually addresses the root cause
"""


def select_agent(escalation_level: str) -> str:
    """Select agent slug based on escalation level.

    Args:
        escalation_level: 'WORKER' or 'SUPERVISOR'

    Returns:
        Agent slug ('worker' or 'supervisor')
    """
    return "worker" if escalation_level == "WORKER" else "supervisor"


def get_temperature(escalation_level: str) -> float:
    """Get temperature setting based on escalation level.

    Args:
        escalation_level: 'WORKER' or 'SUPERVISOR'

    Returns:
        Temperature value (0.2 for WORKER, 0.3 for SUPERVISOR)
    """
    return 0.2 if escalation_level == "WORKER" else 0.3


def enhance_prompt_for_supervisor(base_prompt: str) -> str:
    """Enhance prompt with supervisor-level guidance.

    Args:
        base_prompt: Base prompt from build_fix_prompt

    Returns:
        Enhanced prompt with additional context for supervisor attempts
    """
    return SUPERVISOR_ENHANCEMENT.format(base_prompt=base_prompt)
