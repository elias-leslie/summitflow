"""Extraction prompts management endpoints for roundtable."""

from datetime import datetime

from fastapi import APIRouter, HTTPException

from ...storage import extraction_prompts as extraction_prompts_storage
from .models import (
    ExtractionPromptConfig,
    ExtractionPromptsExport,
    UpdateExtractionPromptRequest,
)

router = APIRouter()


@router.get(
    "/projects/{project_id}/roundtable/extraction-prompts",
    response_model=list[ExtractionPromptConfig],
)
async def list_extraction_prompts(project_id: str) -> list[ExtractionPromptConfig]:
    """List all extraction prompts for a project.

    Returns all prompt types with their current configuration.
    If a custom prompt exists, it's returned; otherwise, the default is used.
    The is_default flag indicates whether the prompt is using default configuration.
    """
    prompts = extraction_prompts_storage.get_all_extraction_prompts(project_id)
    return [
        ExtractionPromptConfig(
            prompt_type=p["prompt_type"],
            prompt_text=p["prompt_text"],
            primary_agent=p.get("primary_agent", "claude"),
            primary_model=p.get("primary_model", "claude-sonnet-4-5"),
            verification_enabled=p.get("verification_enabled", False),
            verification_agent=p.get("verification_agent"),
            verification_model=p.get("verification_model"),
            verification_prompt=p.get("verification_prompt"),
            is_default=p.get("is_default", True),
            created_at=p.get("created_at").isoformat() if p.get("created_at") else None,
            updated_at=p.get("updated_at").isoformat() if p.get("updated_at") else None,
        )
        for p in prompts
    ]


# NOTE: Export must come BEFORE {prompt_type} routes to avoid route conflict
@router.get(
    "/projects/{project_id}/roundtable/extraction-prompts/export",
)
async def export_extraction_prompts(
    project_id: str, format: str = "json"
) -> ExtractionPromptsExport:
    """Export all extraction prompts for backup/sharing.

    Currently only JSON format is supported.
    """
    if format != "json":
        raise HTTPException(status_code=400, detail="Only 'json' format is currently supported")

    prompts = extraction_prompts_storage.get_all_extraction_prompts(project_id)

    return ExtractionPromptsExport(
        project_id=project_id,
        exported_at=datetime.utcnow().isoformat(),
        prompts=[
            ExtractionPromptConfig(
                prompt_type=p["prompt_type"],
                prompt_text=p["prompt_text"],
                primary_agent=p.get("primary_agent", "claude"),
                primary_model=p.get("primary_model", "claude-sonnet-4-5"),
                verification_enabled=p.get("verification_enabled", False),
                verification_agent=p.get("verification_agent"),
                verification_model=p.get("verification_model"),
                verification_prompt=p.get("verification_prompt"),
                is_default=p.get("is_default", True),
                created_at=p.get("created_at").isoformat() if p.get("created_at") else None,
                updated_at=p.get("updated_at").isoformat() if p.get("updated_at") else None,
            )
            for p in prompts
        ],
    )


@router.get(
    "/projects/{project_id}/roundtable/extraction-prompts/{prompt_type}",
    response_model=ExtractionPromptConfig,
)
async def get_extraction_prompt(project_id: str, prompt_type: str) -> ExtractionPromptConfig:
    """Get a specific extraction prompt by type.

    Valid prompt types: feature_extraction, vision_extraction, goals_extraction
    """
    valid_types = ["feature_extraction", "vision_extraction", "goals_extraction"]
    if prompt_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt type. Must be one of: {', '.join(valid_types)}",
        )

    prompt = extraction_prompts_storage.get_extraction_prompt(project_id, prompt_type)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt type not found")

    return ExtractionPromptConfig(
        prompt_type=prompt["prompt_type"],
        prompt_text=prompt["prompt_text"],
        primary_agent=prompt.get("primary_agent", "claude"),
        primary_model=prompt.get("primary_model", "claude-sonnet-4-5"),
        verification_enabled=prompt.get("verification_enabled", False),
        verification_agent=prompt.get("verification_agent"),
        verification_model=prompt.get("verification_model"),
        verification_prompt=prompt.get("verification_prompt"),
        is_default=prompt.get("is_default", True),
        created_at=prompt.get("created_at").isoformat() if prompt.get("created_at") else None,
        updated_at=prompt.get("updated_at").isoformat() if prompt.get("updated_at") else None,
    )


@router.put(
    "/projects/{project_id}/roundtable/extraction-prompts/{prompt_type}",
    response_model=ExtractionPromptConfig,
)
async def update_extraction_prompt(
    project_id: str, prompt_type: str, request: UpdateExtractionPromptRequest
) -> ExtractionPromptConfig:
    """Create or update an extraction prompt.

    Valid prompt types: feature_extraction, vision_extraction, goals_extraction
    """
    valid_types = ["feature_extraction", "vision_extraction", "goals_extraction"]
    if prompt_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt type. Must be one of: {', '.join(valid_types)}",
        )

    valid_agents = ["claude", "gemini"]
    if request.primary_agent not in valid_agents:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid primary_agent. Must be one of: {', '.join(valid_agents)}",
        )

    if (
        request.verification_enabled
        and request.verification_agent
        and request.verification_agent not in valid_agents
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verification_agent. Must be one of: {', '.join(valid_agents)}",
        )

    result = extraction_prompts_storage.upsert_extraction_prompt(
        project_id=project_id,
        prompt_type=prompt_type,
        prompt_text=request.prompt_text,
        primary_agent=request.primary_agent,
        primary_model=request.primary_model,
        verification_enabled=request.verification_enabled,
        verification_agent=request.verification_agent,
        verification_model=request.verification_model,
        verification_prompt=request.verification_prompt,
    )

    return ExtractionPromptConfig(
        prompt_type=result["prompt_type"],
        prompt_text=result["prompt_text"],
        primary_agent=result["primary_agent"],
        primary_model=result["primary_model"],
        verification_enabled=result["verification_enabled"],
        verification_agent=result.get("verification_agent"),
        verification_model=result.get("verification_model"),
        verification_prompt=result.get("verification_prompt"),
        is_default=False,
        created_at=result.get("created_at").isoformat() if result.get("created_at") else None,
        updated_at=result.get("updated_at").isoformat() if result.get("updated_at") else None,
    )


@router.delete(
    "/projects/{project_id}/roundtable/extraction-prompts/{prompt_type}",
)
async def delete_extraction_prompt(project_id: str, prompt_type: str) -> dict:
    """Delete a custom extraction prompt (revert to default).

    Valid prompt types: feature_extraction, vision_extraction, goals_extraction
    """
    valid_types = ["feature_extraction", "vision_extraction", "goals_extraction"]
    if prompt_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt type. Must be one of: {', '.join(valid_types)}",
        )

    deleted = extraction_prompts_storage.delete_extraction_prompt(project_id, prompt_type)
    if not deleted:
        # Not an error - just means they were already using default
        return {"reverted_to_default": True, "prompt_type": prompt_type}

    return {"deleted": True, "reverted_to_default": True, "prompt_type": prompt_type}
