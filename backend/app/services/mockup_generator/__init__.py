"""Mockup generator service for design audit workflows.

Uses Agent Hub for image generation (Gemini) with Claude HTML as fallback.
Mockups are stored in the mockups table.

This module is organized as follows:
- models.py: Data models (MockupResult, DesignAnalysisResult)
- prompts.py: Prompt builders for different use cases
- renderers/: Image and HTML mockup generators
- analysis/: Design analysis and screenshot tools
- storage_helpers.py: Storage utilities
- _workflows.py: Internal workflow helpers (analyze_page_design logic)
"""

from __future__ import annotations

from ...logging_config import get_logger
from ._workflows import get_design_standard, run_analyze_page_design
from .models import DesignAnalysisResult, MockupResult
from .renderers import generate_mockup_claude_fallback, generate_mockup_gemini

logger = get_logger(__name__)


def generate_mockup(
    project_id: str,
    explorer_entry_id: int,
    standards_id: str = "base",
    design_direction: str | None = None,
    page_info: dict | None = None,
) -> MockupResult:
    """Generate a mockup for a page using design standards.

    Uses Agent Hub (Gemini) as primary, Claude HTML as fallback.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID for the page
        standards_id: Design standard ID to use (default: "base")
        design_direction: Optional specific design direction
        page_info: Page info (if not provided, fetched from explorer)

    Returns:
        MockupResult with evidence details
    """
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

    design_standard = get_design_standard(project_id, standards_id)
    if not design_standard:
        return MockupResult(
            success=False,
            error=f"Design standard '{standards_id}' not found",
        )

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


async def analyze_page_design(
    project_id: str,
    page_url: str,
    page_path: str | None = None,
) -> DesignAnalysisResult:
    """Analyze a page's design and generate improvement recommendations.

    Delegates to _workflows.run_analyze_page_design for the full workflow:
    1. Capture screenshot of the page
    2. Fetch design standards for the project
    3. Analyze screenshot against standards using vision
    4. Store mockup record with screenshot and recommendations

    Args:
        project_id: Project ID
        page_url: Full URL to analyze
        page_path: Optional page path (for storage, defaults to URL path)

    Returns:
        DesignAnalysisResult with mockup details
    """
    return await run_analyze_page_design(project_id, page_url, page_path)


__all__ = [
    "DesignAnalysisResult",
    "MockupResult",
    "analyze_page_design",
    "generate_mockup",
    "generate_mockup_claude_fallback",
    "generate_mockup_gemini",
]
