"""Mockup generator service for design audit workflows.

Uses Gemini 3 Pro Image for mockup generation with Claude as fallback.
Mockups are stored as evidence records with type='mockup'.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google import genai

from ..constants import CLAUDE_SONNET, GEMINI_IMAGE
from ..logging_config import get_logger
from ..storage import evidence as evidence_storage

logger = get_logger(__name__)

# Directory for storing mockup images
MOCKUP_BASE_DIR = Path("/tmp/summitflow/mockups")


@dataclass
class MockupResult:
    """Result of mockup generation."""

    success: bool
    evidence_id: str | None = None
    db_id: int | None = None
    image_path: str | None = None
    error: str | None = None
    generator: str | None = None
    generation_time_ms: int = 0


def _check_credentials() -> bool:
    """Check if Gemini credentials are available."""
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return True

    gemini_env = Path.home() / ".gemini" / ".env"
    if gemini_env.exists():
        with open(gemini_env) as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    key = line.strip().split("=", 1)[1]
                    os.environ["GOOGLE_API_KEY"] = key
                    return True

    return False


def _get_gemini_client() -> genai.Client:
    """Get or create Gemini client."""
    from google import genai

    return genai.Client()


def _build_mockup_prompt(
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> str:
    """Build the prompt for mockup generation.

    Args:
        page_info: Page metadata from explorer (path, title, etc.)
        design_standard: Design standard with rules
        design_direction: Optional specific design direction

    Returns:
        Formatted prompt for image generation
    """
    page_path = page_info.get("path", "/")
    page_title = page_info.get("name", "Page")
    page_description = page_info.get("description", "")

    # Extract key rules from design standard
    rules = design_standard.get("rules", [])
    color_rules = [r for r in rules if r.get("category") == "colors"]
    typography_rules = [r for r in rules if r.get("category") == "typography"]
    layout_rules = [r for r in rules if r.get("category") == "layout"]
    component_rules = [r for r in rules if r.get("category") == "components"]

    def format_rules(rule_list: list[dict[str, Any]], max_rules: int = 3) -> str:
        if not rule_list:
            return "None specified"
        return "\n".join(
            f"- {r.get('name', 'Rule')}: {r.get('value', '')}" for r in rule_list[:max_rules]
        )

    prompt = f"""Generate a high-fidelity UI mockup for a web application page.

PAGE CONTEXT:
- Path: {page_path}
- Title: {page_title}
- Description: {page_description}

DESIGN STANDARD: {design_standard.get("name", "Default")}

COLOR PALETTE:
{format_rules(color_rules)}

TYPOGRAPHY:
{format_rules(typography_rules)}

LAYOUT RULES:
{format_rules(layout_rules)}

COMPONENT PATTERNS:
{format_rules(component_rules)}

REQUIREMENTS:
1. Create a complete, professional UI mockup at 1920x1080 resolution
2. Use a dark theme with the specified color palette
3. Include realistic content (not lorem ipsum)
4. Show proper spacing, alignment, and visual hierarchy
5. Include navigation, content area, and any relevant UI elements
6. Text should be legible and rendered clearly

{f"DESIGN DIRECTION: {design_direction}" if design_direction else ""}

Output a single image that represents the target design state for this page."""

    return prompt


def generate_mockup_gemini(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, Any],
    design_standard: dict[str, Any],
    design_direction: str | None = None,
) -> MockupResult:
    """Generate mockup using Gemini 3 Pro Image.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        page_info: Page metadata from explorer
        design_standard: Design standard with rules
        design_direction: Optional specific design direction

    Returns:
        MockupResult with evidence details
    """
    import time

    start_time = time.monotonic()

    if not _check_credentials():
        return MockupResult(
            success=False,
            error="Gemini credentials not available",
        )

    try:
        client = _get_gemini_client()
        prompt = _build_mockup_prompt(page_info, design_standard, design_direction)

        # Generate image using Gemini
        response = client.models.generate_content(
            model=GEMINI_IMAGE,
            contents=prompt,
            config={
                "response_modalities": ["IMAGE", "TEXT"],
                "temperature": 0.7,
            },
        )

        # Extract image from response
        image_data = None
        candidates = response.candidates
        if candidates and candidates[0].content and candidates[0].content.parts:
            for part in candidates[0].content.parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data and getattr(inline_data, "mime_type", "").startswith("image/"):
                    image_data = inline_data.data
                    break

        if not image_data:
            return MockupResult(
                success=False,
                error="No image generated in response",
                generator="gemini",
                generation_time_ms=int((time.monotonic() - start_time) * 1000),
            )

        # Save image to file
        evidence_id = evidence_storage.generate_evidence_id()
        mockup_dir = MOCKUP_BASE_DIR / project_id / evidence_id
        mockup_dir.mkdir(parents=True, exist_ok=True)

        image_path = mockup_dir / "mockup.png"
        image_bytes = base64.b64decode(image_data)
        image_path.write_bytes(image_bytes)

        # Store as evidence
        from ..storage.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            db_id, evidence_id, captured_at = evidence_storage.insert_evidence_record(
                cur,
                project_id=project_id,
                file_path=str(image_path),
                file_size_bytes=len(image_bytes),
                explorer_entry_id=explorer_entry_id,
                evidence_type="mockup",
                mockup_status="pending_approval",
                environment="generated",
            )
            conn.commit()

        generation_time = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "mockup_generated",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            evidence_id=evidence_id,
            generator="gemini",
            generation_time_ms=generation_time,
        )

        return MockupResult(
            success=True,
            evidence_id=evidence_id,
            db_id=db_id,
            image_path=str(image_path),
            generator="gemini",
            generation_time_ms=generation_time,
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
        MockupResult with evidence details
    """
    import time

    from .agent_hub_client import get_agent

    start_time = time.monotonic()

    try:
        claude = get_agent("claude", model=CLAUDE_SONNET)
        prompt = _build_mockup_prompt(page_info, design_standard, design_direction)

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
            max_tokens=8000,
            temperature=0.7,
        )

        html_content = response.content.strip()

        # Extract HTML if wrapped in code blocks
        if "```html" in html_content:
            html_content = html_content.split("```html")[1].split("```")[0].strip()
        elif "```" in html_content:
            html_content = html_content.split("```")[1].split("```")[0].strip()

        # Save HTML to file
        evidence_id = evidence_storage.generate_evidence_id()
        mockup_dir = MOCKUP_BASE_DIR / project_id / evidence_id
        mockup_dir.mkdir(parents=True, exist_ok=True)

        html_path = mockup_dir / "mockup.html"
        html_path.write_text(html_content)

        # Store as evidence
        from ..storage.connection import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            db_id, evidence_id, captured_at = evidence_storage.insert_evidence_record(
                cur,
                project_id=project_id,
                file_path=str(html_path),
                file_size_bytes=len(html_content.encode()),
                explorer_entry_id=explorer_entry_id,
                evidence_type="mockup",
                mockup_status="pending_approval",
                environment="generated",
            )
            conn.commit()

        generation_time = int((time.monotonic() - start_time) * 1000)

        logger.info(
            "mockup_generated",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            evidence_id=evidence_id,
            generator="claude",
            generation_time_ms=generation_time,
        )

        return MockupResult(
            success=True,
            evidence_id=evidence_id,
            db_id=db_id,
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


def generate_mockup(
    project_id: str,
    explorer_entry_id: int,
    standards_id: str = "base",
    design_direction: str | None = None,
    page_info: dict[str, Any] | None = None,
) -> MockupResult:
    """Generate a mockup for a page using design standards.

    Uses Gemini 3 Pro Image as primary, Claude HTML as fallback.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        standards_id: Design standard ID to use (default: "base")
        design_direction: Optional specific design direction
        page_info: Page info (if not provided, fetched from explorer)

    Returns:
        MockupResult with evidence details
    """
    # Get page info if not provided
    if page_info is None:
        from ..storage.explorer_entries import get_entry_by_id

        entry = get_entry_by_id(explorer_entry_id)
        if not entry:
            return MockupResult(
                success=False,
                error=f"Explorer entry {explorer_entry_id} not found",
            )
        page_info = {
            "path": entry.get("path"),
            "name": entry.get("name"),
            "description": entry.get("description"),
        }

    # Get design standard
    from ..storage.design_standards import get_base_standard, get_project_standard

    design_standard = None
    if standards_id == "base":
        design_standard = get_base_standard()
    else:
        design_standard = get_project_standard(project_id, standards_id)

    if not design_standard:
        design_standard = get_base_standard()

    if not design_standard:
        return MockupResult(
            success=False,
            error=f"Design standard '{standards_id}' not found",
        )

    # Try Gemini first, fallback to Claude
    result = generate_mockup_gemini(
        project_id=project_id,
        explorer_entry_id=explorer_entry_id,
        page_info=page_info,
        design_standard=design_standard,
        design_direction=design_direction,
    )

    if not result.success:
        logger.info(
            "falling_back_to_claude",
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            gemini_error=result.error,
        )
        result = generate_mockup_claude_fallback(
            project_id=project_id,
            explorer_entry_id=explorer_entry_id,
            page_info=page_info,
            design_standard=design_standard,
            design_direction=design_direction,
        )

    return result


__all__ = [
    "MockupResult",
    "generate_mockup",
    "generate_mockup_claude_fallback",
    "generate_mockup_gemini",
]
