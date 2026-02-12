"""Gemini-based mockup image generation."""

from __future__ import annotations

import base64
import time
from typing import Any

from agent_hub.exceptions import AgentHubError

from ....constants import GEMINI_IMAGE
from ....logging_config import get_logger
from ....storage import mockups as mockups_storage
from ...agent_hub_client import get_sync_client
from ..models import MockupResult
from ..prompts import build_mockup_prompt
from ..storage_helpers import generate_mockup_id, get_mockup_directory

logger = get_logger(__name__)


def generate_mockup_gemini(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> MockupResult:
    """Generate mockup using Agent Hub image generation (Gemini backend).

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        page_info: Page metadata from explorer
        design_standard: Design standard with rules
        design_direction: Optional specific design direction

    Returns:
        MockupResult with mockup details
    """
    start_time = time.monotonic()

    try:
        client = get_sync_client()
        prompt = build_mockup_prompt(page_info, design_standard, design_direction)

        # Generate image using Agent Hub
        response = client.generate_image(
            prompt=prompt,
            project_id="summitflow",
            purpose="mockup_generation",
            model=GEMINI_IMAGE,
            size="1920x1080",
        )

        # Decode base64 image data
        image_bytes = base64.b64decode(response.image_base64)

        # Determine file extension from mime type
        ext = "png"
        if response.mime_type == "image/jpeg":
            ext = "jpg"
        elif response.mime_type == "image/webp":
            ext = "webp"

        # Save image to file
        mockup_id = generate_mockup_id()
        mockup_dir = get_mockup_directory(project_id, mockup_id)
        mockup_dir.mkdir(parents=True, exist_ok=True)

        image_path = mockup_dir / f"mockup.{ext}"
        image_path.write_bytes(image_bytes)

        generation_time = int((time.monotonic() - start_time) * 1000)

        # Store in mockups table
        page_path = page_info.get("path", "/")
        page_name = page_info.get("name", "Generated mockup")

        mockup = mockups_storage.create_mockup(
            project_id=project_id,
            name=f"Mockup: {page_name}",
            description=f"Generated mockup for {page_path}",
            mockup_type="page",
            file_path=str(image_path),
            page_path=page_path,
            generator="gemini",
            generation_prompt=prompt,
            generation_time_ms=generation_time,
        )

        logger.info(
            "mockup_generated",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            mockup_id=mockup["mockup_id"],
            generator="gemini",
            generation_time_ms=generation_time,
            session_id=response.session_id,
        )

        return MockupResult(
            success=True,
            mockup_id=mockup["mockup_id"],
            db_id=mockup["id"],
            image_path=str(image_path),
            generator="gemini",
            generation_time_ms=generation_time,
        )

    except AgentHubError as e:
        logger.error(
            "mockup_generation_failed",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            generator="gemini",
            error=str(e),
        )
        return MockupResult(
            success=False,
            error=str(e),
            generator="gemini",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )
    except Exception as e:
        logger.error(
            "mockup_generation_failed",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            generator="gemini",
            error=str(e),
        )
        return MockupResult(
            success=False,
            error=str(e),
            generator="gemini",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )


__all__ = ["generate_mockup_gemini"]
