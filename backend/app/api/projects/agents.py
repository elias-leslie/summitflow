"""Agent configuration endpoints for projects."""

from typing import Any

from fastapi import APIRouter, HTTPException

from ...constants import VALID_CLAUDE_MODELS, VALID_GEMINI_MODELS
from ...storage import agent_configs
from ..dependencies import validate_project_exists
from .models import AgentConfigResponse, AgentConfigUpdate

router = APIRouter()


@router.get("/{project_id}/agents", response_model=AgentConfigResponse)
async def get_agent_config(project_id: str) -> AgentConfigResponse:
    """Get agent configuration for a project."""
    validate_project_exists(project_id)
    config = agent_configs.get_agent_config(project_id)
    return AgentConfigResponse(**config)


@router.patch("/{project_id}/agents", response_model=AgentConfigResponse)
async def update_agent_config(project_id: str, update: AgentConfigUpdate) -> AgentConfigResponse:
    """Update agent configuration for a project."""
    validate_project_exists(project_id)

    # Build config update dict from non-None values
    config_update: dict[str, Any] = {}
    if update.claude_enabled is not None:
        config_update["claude_enabled"] = update.claude_enabled
    if update.gemini_enabled is not None:
        config_update["gemini_enabled"] = update.gemini_enabled
    if update.default_agent is not None:
        if update.default_agent not in ("claude", "gemini"):
            raise HTTPException(
                status_code=400, detail="default_agent must be 'claude' or 'gemini'"
            )
        config_update["default_agent"] = update.default_agent
    if update.claude_model is not None:
        if update.claude_model not in VALID_CLAUDE_MODELS:
            raise HTTPException(
                status_code=400, detail=f"claude_model must be one of: {VALID_CLAUDE_MODELS}"
            )
        config_update["claude_model"] = update.claude_model
    if update.gemini_model is not None:
        if update.gemini_model not in VALID_GEMINI_MODELS:
            raise HTTPException(
                status_code=400, detail=f"gemini_model must be one of: {VALID_GEMINI_MODELS}"
            )
        config_update["gemini_model"] = update.gemini_model

    # Component management
    if update.component_source is not None:
        valid_sources = ("pages", "endpoints", "directories", "manual")
        if update.component_source not in valid_sources:
            raise HTTPException(
                status_code=400,
                detail=f"component_source must be one of: {valid_sources}",
            )
        config_update["component_source"] = update.component_source

    # Autonomous execution
    if update.autonomous_enabled is not None:
        config_update["autonomous_enabled"] = update.autonomous_enabled

    if not config_update:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = agent_configs.update_agent_config(project_id, config_update)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Agent config for project {project_id} not found")
    return AgentConfigResponse(**updated)


@router.get("/{project_id}/agents/enabled", response_model=list[str])
async def get_enabled_agents(project_id: str) -> list[str]:
    """Get list of enabled agents for a project."""
    validate_project_exists(project_id)
    return agent_configs.get_enabled_agents(project_id)
