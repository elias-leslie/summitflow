"""Asset generation endpoint for mockups API.

Generates images via Agent Hub's image generation agent, with prompt
templates for game assets (sprites, sheets, environments).
"""

from __future__ import annotations

import base64
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..constants import AGENT_IMAGE_GEN
from ..logging_config import get_logger
from ..services.agent_hub_client import get_sync_client
from ..services.mockup_generator.revisions import MockupRevisionContentError, rerun_mockup
from ..services.mockup_generator.sprite_prompts import (
    build_environment_prompt,
    build_sheet_prompt,
    build_sprite_prompt,
)
from ..services.mockup_generator.storage_helpers import (
    generate_mockup_id,
    get_mockup_directory,
)
from ..storage import mockups as mockups_storage
from .mockups_models import RerunMockupRequest, RerunMockupResponse
from .mockups_utils import to_response

logger = get_logger(__name__)

router = APIRouter()

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

# Prompt builders keyed by mockup_type
_PROMPT_BUILDERS = {
    "sprite": lambda req: build_sprite_prompt(req.prompt, req.style),
    "sheet": lambda req: build_sheet_prompt(req.prompt, style=req.style),
    "illustration": lambda req: build_sprite_prompt(req.prompt, req.style),
    "icon": lambda req: build_sprite_prompt(req.prompt, req.style),
    "page": lambda req: build_environment_prompt(
        req.prompt, *(_parse_size(req.size)), req.style,
    ),
    "layout": lambda req: build_environment_prompt(
        req.prompt, *(_parse_size(req.size)), req.style,
    ),
}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class GenerateAssetRequest(BaseModel):
    """Request body for asset generation."""

    prompt: str
    name: str
    mockup_type: str = "sprite"
    agent_slug: str | None = None
    model: str | None = None
    size: str = "1024x1024"
    style: str | None = None


class GenerateAssetResponse(BaseModel):
    """Response from asset generation."""

    success: bool
    mockup_id: str | None = None
    file_path: str | None = None
    error: str | None = None
    generation_time_ms: int = 0
    model_used: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_size(size: str) -> tuple[int, int]:
    """Parse 'WIDTHxHEIGHT' string into (width, height)."""
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1024, 1024


def _build_merged_prompt(request: GenerateAssetRequest) -> str:
    """Build the final prompt by selecting the right template."""
    builder = _PROMPT_BUILDERS.get(request.mockup_type)
    if builder:
        return builder(request)
    # Fallback: raw prompt with style
    if request.style:
        return f"{request.prompt}\nArt style: {request.style}"
    return request.prompt


def _resolve_agent_slug(agent_slug: str | None, legacy_agent_or_model: str | None = None) -> str:
    """Resolve an image generation agent slug.

    Legacy model IDs are intentionally ignored; Agent Hub owns image model choice.
    """
    candidate = agent_slug or legacy_agent_or_model
    if candidate and "/" not in candidate:
        return candidate.removeprefix("agent:")
    return AGENT_IMAGE_GEN


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/mockups/generate-asset",
    response_model=GenerateAssetResponse,
)
async def generate_asset(
    project_id: str,
    request: GenerateAssetRequest,
) -> GenerateAssetResponse:
    """Generate a game asset image and store it as a mockup.

    Merges the user prompt with game-asset-specific templates, calls
    Agent Hub image generation, saves the result to disk,
    and creates a mockup DB record.
    """
    start_time = time.monotonic()
    agent_slug = _resolve_agent_slug(request.agent_slug, request.model)
    merged_prompt = _build_merged_prompt(request)

    try:
        client = get_sync_client()
        response = client.generate_image(
            prompt=merged_prompt,
            project_id=project_id,
            purpose="asset_generation",
            agent_slug=agent_slug,
            size=request.size,
            style=request.style,
        )

        image_bytes = base64.b64decode(response.image_base64)
        ext = _MIME_TO_EXT.get(response.mime_type, "png")

        mockup_id = generate_mockup_id()
        mockup_dir = get_mockup_directory(project_id, mockup_id)
        mockup_dir.mkdir(parents=True, exist_ok=True)
        image_path = mockup_dir / f"asset.{ext}"
        image_path.write_bytes(image_bytes)

        generation_time = int((time.monotonic() - start_time) * 1000)

        mockup = mockups_storage.create_mockup(
            project_id=project_id,
            name=request.name,
            description=f"Generated {request.mockup_type}: {request.prompt[:200]}",
            mockup_type=request.mockup_type,
            file_path=str(image_path),
            generator="image-gen",
            generation_prompt=merged_prompt,
            generation_time_ms=generation_time,
        )

        logger.info(
            "asset_generated",
            project_id=project_id,
            mockup_id=mockup["mockup_id"],
            mockup_type=request.mockup_type,
            agent_slug=agent_slug,
            model=response.model,
            generation_time_ms=generation_time,
        )

        return GenerateAssetResponse(
            success=True,
            mockup_id=mockup["mockup_id"],
            file_path=str(image_path),
            generation_time_ms=generation_time,
            model_used=response.model,
        )

    except Exception as e:
        generation_time = int((time.monotonic() - start_time) * 1000)
        logger.error(
            "asset_generation_failed",
            project_id=project_id,
            error=str(e),
            agent_slug=agent_slug,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Image generation failed: {e}",
        ) from e


@router.post(
    "/projects/{project_id}/mockups/{mockup_id}/rerun",
    response_model=RerunMockupResponse,
)
async def rerun_mockup_endpoint(
    project_id: str,
    mockup_id: str,
    request: RerunMockupRequest,
) -> RerunMockupResponse:
    """Create a new Agent Hub-generated revision for an existing mockup."""
    try:
        result = rerun_mockup(project_id, mockup_id, request.notes)
    except ValueError as e:
        message = str(e)
        status_code = 404 if message == "Mockup not found" else 400
        raise HTTPException(status_code=status_code, detail=message) from e
    except MockupRevisionContentError as e:
        logger.warning(
            "mockup_revision_failed",
            project_id=project_id,
            mockup_id=mockup_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Mockup revision did not produce revised content: {e}",
        ) from e
    except Exception as e:
        logger.error(
            "mockup_revision_failed",
            project_id=project_id,
            mockup_id=mockup_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail=f"Mockup revision generation failed: {e}",
        ) from e

    return RerunMockupResponse(
        success=True,
        mockup=to_response(result.mockup),
        agent_slug=result.agent_slug,
        model_used=result.model_used,
        provider=result.provider,
        session_id=result.session_id,
        generation_time_ms=result.generation_time_ms,
    )
