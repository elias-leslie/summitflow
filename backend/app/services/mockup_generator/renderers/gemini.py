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

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_GENERATOR_NAME = "gemini"
_AGENT_HUB_PROJECT = "summitflow"
_GENERATION_PURPOSE = "mockup_generation"
_IMAGE_SIZE = "1920x1080"
_MOCKUP_TYPE = "page"
_DEFAULT_PAGE_PATH = "/"
_DEFAULT_PAGE_NAME = "Generated mockup"

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/webp": "webp",
}
_DEFAULT_IMAGE_EXT = "png"

_LOG_GENERATED = "mockup_generated"
_LOG_FAILED = "mockup_generation_failed"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_image_extension(mime_type: str) -> str:
    """Return the file extension for a given MIME type."""
    return _MIME_TO_EXT.get(mime_type, _DEFAULT_IMAGE_EXT)


def _call_image_api(prompt: str) -> Any:
    """Call Agent Hub image generation and return the response."""
    client = get_sync_client()
    return client.generate_image(
        prompt=prompt,
        project_id=_AGENT_HUB_PROJECT,
        purpose=_GENERATION_PURPOSE,
        model=GEMINI_IMAGE,
        size=_IMAGE_SIZE,
    )


def _save_image(project_id: str, image_bytes: bytes, ext: str) -> tuple[str, str]:
    """Persist image bytes to disk and return (mockup_id, file_path)."""
    mockup_id = generate_mockup_id()
    mockup_dir = get_mockup_directory(project_id, mockup_id)
    mockup_dir.mkdir(parents=True, exist_ok=True)
    image_path = mockup_dir / f"mockup.{ext}"
    image_path.write_bytes(image_bytes)
    return mockup_id, str(image_path)


def _store_mockup_record(
    project_id: str,
    page_info: dict[str, Any],
    prompt: str,
    image_path: str,
    generation_time: int,
    session_id: str,
) -> dict[str, Any]:
    """Write the mockup record to the database and emit a log line."""
    page_path = page_info.get("path", _DEFAULT_PAGE_PATH)
    page_name = page_info.get("name", _DEFAULT_PAGE_NAME)

    mockup = mockups_storage.create_mockup(
        project_id=project_id,
        name=f"Mockup: {page_name}",
        description=f"Generated mockup for {page_path}",
        mockup_type=_MOCKUP_TYPE,
        file_path=image_path,
        page_path=page_path,
        generator=_GENERATOR_NAME,
        generation_prompt=prompt,
        generation_time_ms=generation_time,
    )

    logger.info(
        _LOG_GENERATED,
        project_id=project_id,
        mockup_id=mockup["mockup_id"],
        generator=_GENERATOR_NAME,
        generation_time_ms=generation_time,
        session_id=session_id,
    )
    return mockup


def _build_success_result(
    mockup: dict[str, Any],
    image_path: str,
    generation_time: int,
) -> MockupResult:
    """Build a successful MockupResult."""
    return MockupResult(
        success=True,
        mockup_id=mockup["mockup_id"],
        db_id=mockup["id"],
        image_path=image_path,
        generator=_GENERATOR_NAME,
        generation_time_ms=generation_time,
    )


def _build_error_result(
    project_id: str,
    explorer_entry_id: int,
    error: Exception,
    generation_time: int,
) -> MockupResult:
    """Log the error and return a failed MockupResult."""
    logger.error(
        _LOG_FAILED,
        project_id=project_id,
        explorer_entry_id=explorer_entry_id,
        generator=_GENERATOR_NAME,
        error=str(error),
    )
    return MockupResult(
        success=False,
        error=str(error),
        generator=_GENERATOR_NAME,
        generation_time_ms=generation_time,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
        prompt = build_mockup_prompt(page_info, design_standard, design_direction)
        response = _call_image_api(prompt)

        image_bytes = base64.b64decode(response.image_base64)
        ext = _get_image_extension(response.mime_type)
        _mockup_id, image_path = _save_image(project_id, image_bytes, ext)

        generation_time = int((time.monotonic() - start_time) * 1000)
        mockup = _store_mockup_record(
            project_id=project_id,
            page_info=page_info,
            prompt=prompt,
            image_path=image_path,
            generation_time=generation_time,
            session_id=response.session_id,
        )
        return _build_success_result(mockup, image_path, generation_time)

    except Exception as e:
        return _build_error_result(
            project_id,
            explorer_entry_id,
            e,
            int((time.monotonic() - start_time) * 1000),
        )


__all__ = ["generate_mockup_gemini"]
