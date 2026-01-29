"""Claude-based HTML mockup generation (fallback)."""

from __future__ import annotations

import time
from typing import Any

from ...agent_hub_client import get_agent
from ...constants import CLAUDE_SONNET
from ...logging_config import get_logger
from ...storage import mockups as mockups_storage
from ..models import MockupResult
from ..prompts import build_mockup_prompt
from ..storage_helpers import generate_mockup_id, get_mockup_directory

logger = get_logger(__name__)


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

    try:
        claude = get_agent("claude", model=CLAUDE_SONNET)
        prompt = build_mockup_prompt(page_info, design_standard, design_direction)

        # Modify prompt for HTML output
        html_prompt = f"""{prompt}

Since I cannot generate images, create a complete HTML/CSS mockup that:
1. Uses inline styles or a <style> block
2. Implements the color palette and typography specified
3. Creates a realistic, interactive prototype
4. Is self-contained in a single HTML file

Output ONLY the HTML code, no explanation."""

        response = claude.generate(
            prompt=html_prompt,
            system="You are a UI designer creating HTML/CSS prototypes. Output only valid HTML.",
            temperature=0.7,
            purpose="mockup_generation",
        )

        html_content = response.content.strip()

        # Extract HTML if wrapped in code blocks
        if "```html" in html_content:
            html_content = html_content.split("```html")[1].split("```")[0].strip()
        elif "```" in html_content:
            html_content = html_content.split("```")[1].split("```")[0].strip()

        # Save HTML to file
        mockup_id = generate_mockup_id()
        mockup_dir = get_mockup_directory(project_id, mockup_id)
        mockup_dir.mkdir(parents=True, exist_ok=True)

        html_path = mockup_dir / "mockup.html"
        html_path.write_text(html_content)

        generation_time = int((time.monotonic() - start_time) * 1000)

        # Store in mockups table
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
