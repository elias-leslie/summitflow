"""Claude-based HTML mockup generation (fallback)."""

from __future__ import annotations

import time
from typing import Any

from ....logging_config import get_logger
from ....storage import mockups as mockups_storage
from ...agent_hub_client import get_agent
from ..models import MockupResult
from ..prompts import build_mockup_prompt
from ..storage_helpers import generate_mockup_id, get_mockup_directory

logger = get_logger(__name__)


def _build_html_prompt(
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None,
) -> str:
    """Build prompt instructing Claude to output HTML/CSS instead of an image."""
    base_prompt = build_mockup_prompt(page_info, design_standard, design_direction)
    return f"""{base_prompt}

Since I cannot generate images, create a complete HTML/CSS mockup that:
1. Uses inline styles or a <style> block
2. Implements the color palette and typography specified
3. Creates a realistic, interactive prototype
4. Is self-contained in a single HTML file

Output ONLY the HTML code, no explanation."""


def _extract_html_from_response(raw: str) -> str:
    """Strip markdown code fences from the Claude response if present."""
    content = raw.strip()
    if "```html" in content:
        return content.split("```html")[1].split("```")[0].strip()
    if "```" in content:
        return content.split("```")[1].split("```")[0].strip()
    return content


def _call_claude_agent(html_prompt: str) -> str:
    """Call the coder agent and return the raw HTML content string."""
    agent = get_agent("coder")
    response = agent.generate(
        prompt=html_prompt,
        temperature=0.7,
        purpose="mockup_generation",
    )
    return response.content


def _save_html_and_store_mockup(
    project_id: str,
    html_content: str,
    html_prompt: str,
    page_info: dict[str, Any],
    generation_time: int,
) -> tuple[dict[str, Any], Any]:
    """Persist HTML to disk and create a DB record; return (mockup dict, html_path)."""
    mockup_id = generate_mockup_id()
    mockup_dir = get_mockup_directory(project_id, mockup_id)
    mockup_dir.mkdir(parents=True, exist_ok=True)

    html_path = mockup_dir / "mockup.html"
    html_path.write_text(html_content)

    page_path = page_info.get("path", "/")
    page_name = page_info.get("name", "Generated mockup")

    mockup = mockups_storage.create_mockup(
        project_id=project_id,
        name=f"Mockup: {page_name}",
        description=f"Generated HTML mockup for {page_path}",
        mockup_type="page",
        file_path=str(html_path),
        content=html_content,
        page_path=page_path,
        generator="claude",
        generation_prompt=html_prompt,
        generation_time_ms=generation_time,
    )
    return mockup, html_path


def _build_success_result(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, Any],
    html_prompt: str,
    start_time: float,
) -> MockupResult:
    """Run generation, store results, log success, and return a MockupResult."""
    raw_content = _call_claude_agent(html_prompt)
    html_content = _extract_html_from_response(raw_content)
    generation_time = int((time.monotonic() - start_time) * 1000)

    mockup, html_path = _save_html_and_store_mockup(
        project_id, html_content, html_prompt, page_info, generation_time
    )
    logger.info(
        "mockup_generated",
        project_id=project_id,
        explorer_entry_id=explorer_entry_id,
        mockup_id=mockup["mockup_id"],
        generator="claude",
        generation_time_ms=generation_time,
    )
    return MockupResult(
        success=True,
        mockup_id=mockup["mockup_id"],
        db_id=mockup["id"],
        image_path=str(html_path),
        generator="claude",
        generation_time_ms=generation_time,
    )


def generate_mockup_claude_fallback(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> MockupResult:
    """Generate HTML mockup using Claude as fallback.

    Generates an HTML/CSS prototype instead of an image.

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
    html_prompt = _build_html_prompt(page_info, design_standard, design_direction)

    try:
        return _build_success_result(
            project_id, explorer_entry_id, page_info, html_prompt, start_time
        )
    except Exception as e:
        logger.error(
            "mockup_generation_failed",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            generator="claude",
            error=str(e),
        )
        return MockupResult(
            success=False,
            error=str(e),
            generator="claude",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )


__all__ = ["generate_mockup_claude_fallback"]
