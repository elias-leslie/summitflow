"""Unified prompts management API endpoints.

Provides CRUD operations for project prompts across all categories:
- spec: Spec pipeline prompts (context discovery, requirements, critique, planning)
- recovery: Error recovery prompts (classify failure, fix code)
- qa: QA prompts (review, fix)
- extraction: Legacy extraction prompts
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..constants import VALID_AGENT_TYPES
from ..storage import prompts as prompts_storage

router = APIRouter(tags=["prompts"])


# ============================================================================
# Models
# ============================================================================


class PromptConfig(BaseModel):
    """Configuration for a prompt."""

    prompt_type: str
    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = "claude-sonnet-4-5"
    category: str = "extraction"
    thinking_budget: int = 0
    tools_enabled: list[str] = []
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class UpdatePromptRequest(BaseModel):
    """Request to update a prompt."""

    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = "claude-sonnet-4-5"
    category: str = "extraction"
    thinking_budget: int = 0
    tools_enabled: list[str] = []


class PromptsExport(BaseModel):
    """Export format for prompts."""

    project_id: str
    exported_at: str
    prompts: list[PromptConfig]


class ImportPromptItem(BaseModel):
    """Single prompt for import."""

    prompt_type: str
    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = "claude-sonnet-4-5"
    category: str = "extraction"
    thinking_budget: int = 0
    tools_enabled: list[str] = []


class ImportPromptsRequest(BaseModel):
    """Request to import prompts."""

    prompts: list[ImportPromptItem]


class ImportPromptsResponse(BaseModel):
    """Response after importing prompts."""

    imported: int
    updated: int
    failed: int
    details: list[dict[str, Any]] = []


# ============================================================================
# Helper functions
# ============================================================================


def _prompt_to_config(prompt: dict[str, Any]) -> PromptConfig:
    """Convert storage dict to PromptConfig model."""
    return PromptConfig(
        prompt_type=prompt["prompt_type"],
        prompt_text=prompt["prompt_text"],
        primary_agent=prompt.get("primary_agent", "claude"),
        primary_model=prompt.get("primary_model", "claude-sonnet-4-5"),
        category=prompt.get("category", "extraction"),
        thinking_budget=prompt.get("thinking_budget", 0),
        tools_enabled=prompt.get("tools_enabled") or [],
        is_default=prompt.get("is_default", True),
        created_at=prompt["created_at"].isoformat() if prompt.get("created_at") else None,
        updated_at=prompt["updated_at"].isoformat() if prompt.get("updated_at") else None,
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.get(
    "/projects/{project_id}/prompts",
    response_model=list[PromptConfig],
)
async def list_prompts(
    project_id: str,
    category: str | None = Query(None, description="Filter by category"),
) -> list[PromptConfig]:
    """List all prompts for a project.

    Returns all prompt types with their current configuration.
    If a custom prompt exists, it's returned; otherwise, the default is used.
    The is_default flag indicates whether the prompt is using default configuration.

    Categories: spec, recovery, qa, extraction
    """
    prompts = prompts_storage.get_all_prompts(project_id, category=category)
    return [_prompt_to_config(p) for p in prompts]


# NOTE: Export must come BEFORE {prompt_type} route to avoid route conflict
@router.get(
    "/projects/{project_id}/prompts/export",
)
async def export_prompts(
    project_id: str,
    category: str | None = Query(None, description="Filter by category"),
) -> PromptsExport:
    """Export all prompts for backup/sharing.

    Returns JSON that can be imported to another project.
    """
    prompts = prompts_storage.get_all_prompts(project_id, category=category)

    return PromptsExport(
        project_id=project_id,
        exported_at=datetime.now(UTC).isoformat(),
        prompts=[_prompt_to_config(p) for p in prompts],
    )


@router.post(
    "/projects/{project_id}/prompts/import",
    response_model=ImportPromptsResponse,
)
async def import_prompts(
    project_id: str,
    request: ImportPromptsRequest,
) -> ImportPromptsResponse:
    """Import prompts from a JSON export.

    Imports all prompts, creating new ones or updating existing ones.
    """
    imported = 0
    updated = 0
    failed = 0
    details: list[dict[str, Any]] = []

    for item in request.prompts:
        try:
            # Check if prompt already exists
            existing = prompts_storage.get_prompt(project_id, item.prompt_type)
            is_update = existing and not existing.get("is_default", True)

            prompts_storage.upsert_prompt(
                project_id=project_id,
                prompt_type=item.prompt_type,
                prompt_text=item.prompt_text,
                primary_agent=item.primary_agent,
                primary_model=item.primary_model,
                category=item.category,
                thinking_budget=item.thinking_budget,
                tools_enabled=item.tools_enabled,
            )

            if is_update:
                updated += 1
                details.append({"prompt_type": item.prompt_type, "status": "updated"})
            else:
                imported += 1
                details.append({"prompt_type": item.prompt_type, "status": "imported"})

        except Exception as e:
            failed += 1
            details.append({"prompt_type": item.prompt_type, "status": "failed", "error": str(e)})

    return ImportPromptsResponse(
        imported=imported,
        updated=updated,
        failed=failed,
        details=details,
    )


@router.get(
    "/projects/{project_id}/prompts/{prompt_type}",
    response_model=PromptConfig,
)
async def get_prompt(project_id: str, prompt_type: str) -> PromptConfig:
    """Get a specific prompt by type."""
    prompt = prompts_storage.get_prompt(project_id, prompt_type)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt type not found")

    return _prompt_to_config(prompt)


@router.put(
    "/projects/{project_id}/prompts/{prompt_type}",
    response_model=PromptConfig,
)
async def update_prompt(
    project_id: str, prompt_type: str, request: UpdatePromptRequest
) -> PromptConfig:
    """Create or update a prompt."""
    if request.primary_agent not in VALID_AGENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid primary_agent. Must be one of: {', '.join(VALID_AGENT_TYPES)}",
        )

    valid_categories = ["spec", "recovery", "qa", "extraction"]
    if request.category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}",
        )

    result = prompts_storage.upsert_prompt(
        project_id=project_id,
        prompt_type=prompt_type,
        prompt_text=request.prompt_text,
        primary_agent=request.primary_agent,
        primary_model=request.primary_model,
        category=request.category,
        thinking_budget=request.thinking_budget,
        tools_enabled=request.tools_enabled,
    )

    return _prompt_to_config(result)


@router.delete(
    "/projects/{project_id}/prompts/{prompt_type}",
)
async def delete_prompt(project_id: str, prompt_type: str) -> dict[str, Any]:
    """Delete a custom prompt (revert to default)."""
    deleted = prompts_storage.delete_prompt(project_id, prompt_type)
    if not deleted:
        # Not an error - just means they were already using default
        return {"reverted_to_default": True, "prompt_type": prompt_type}

    return {"deleted": True, "reverted_to_default": True, "prompt_type": prompt_type}
