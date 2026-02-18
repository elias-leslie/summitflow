"""Quality gate configuration for agent configs."""

from __future__ import annotations

from .agent_configs import get_agent_config


def get_quality_gate_tools(project_id: str) -> list[str]:
    """Get quality gate tool list for a project.

    Args:
        project_id: Project ID

    Returns:
        List of tool names (e.g. ["ruff", "types"]), or empty for default dt mode
    """
    config = get_agent_config(project_id)
    tools = config.get("quality_gate_tools", [])
    if isinstance(tools, list):
        return [str(t) for t in tools]
    return []


def get_quality_gate_mode(project_id: str) -> str:
    """Get quality gate mode for a project.

    Args:
        project_id: Project ID

    Returns:
        Mode string: "quick", "check", or "changed-only"
    """
    config = get_agent_config(project_id)
    mode = str(config.get("quality_gate_mode", "quick"))
    if mode in ("quick", "check", "changed-only"):
        return mode
    return "quick"


def get_quality_gate_fix_enabled(project_id: str) -> bool:
    """Check if auto-fix is enabled for quality gates.

    Args:
        project_id: Project ID

    Returns:
        True if dt --fix is allowed during self-heal (default: True)
    """
    config = get_agent_config(project_id)
    return bool(config.get("quality_gate_fix_enabled", True))


def build_dt_command(
    dt_cmd: str,
    project_id: str,
    *,
    fix: bool = False,
) -> list[str]:
    """Build a dt command from per-project quality gate config.

    Args:
        dt_cmd: Path to dt binary
        project_id: Project ID to read config from
        fix: If True, build a --fix command instead of check

    Returns:
        Command list, e.g. ["dt", "ruff", "types"] or ["dt", "--quick"]
    """
    if fix:
        fix_enabled = get_quality_gate_fix_enabled(project_id)
        if not fix_enabled:
            # Fix disabled — run check-only instead
            return build_dt_command(dt_cmd, project_id, fix=False)
        tools = get_quality_gate_tools(project_id)
        if tools:
            return [dt_cmd, *tools, "--fix"]
        return [dt_cmd, "--fix"]

    tools = get_quality_gate_tools(project_id)
    if tools:
        return [dt_cmd, *tools]

    mode = get_quality_gate_mode(project_id)
    return [dt_cmd, f"--{mode}"]
