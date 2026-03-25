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

from typing import Any

from ...logging_config import get_logger
from ._workflows import get_design_standard, run_analyze_page_design
from .models import DesignAnalysisResult, MockupResult
from .renderers import generate_mockup_claude_fallback, generate_mockup_gemini

logger = get_logger(__name__)


def _fetch_page_info(explorer_entry_id: int) -> dict[str, object] | MockupResult:
    """Fetch page info from explorer entry. Returns dict on success, MockupResult on failure."""
    from ...storage.explorer_entries import get_entry_by_id

    entry = get_entry_by_id(explorer_entry_id)
    if not entry:
        return MockupResult(success=False, error=f"Explorer entry {explorer_entry_id} not found")
    return {"path": entry.get("path"), "name": entry.get("name"), "description": entry.get("description")}


def _run_with_fallback(
    project_id: str,
    explorer_entry_id: int,
    page_info: dict[str, object],
    design_standard: dict[str, Any],
    design_direction: str | None,
) -> MockupResult:
    """Try Gemini first, fall back to Claude HTML if it fails."""
    result = generate_mockup_gemini(
        project_id=project_id,
        explorer_entry_id=explorer_entry_id,
        page_info=page_info,
        design_standard=design_standard,
        design_direction=design_direction,
    )
    if result.success:
        return result
    logger.info("falling_back_to_claude", project_id=project_id, explorer_entry_id=explorer_entry_id, gemini_error=result.error)
    return generate_mockup_claude_fallback(
        project_id=project_id,
        explorer_entry_id=explorer_entry_id,
        page_info=page_info,
        design_standard=design_standard,
        design_direction=design_direction,
    )


def generate_mockup(
    project_id: str,
    explorer_entry_id: int,
    standards_id: str = "base",
    design_direction: str | None = None,
    page_info: dict[str, object] | None = None,
) -> MockupResult:
    """Generate a mockup using design standards (Gemini primary, Claude fallback)."""
    if page_info is None:
        result_or_info = _fetch_page_info(explorer_entry_id)
        if isinstance(result_or_info, MockupResult):
            return result_or_info
        page_info = result_or_info
    design_standard = get_design_standard(project_id, standards_id)
    if not design_standard:
        return MockupResult(success=False, error=f"Design standard '{standards_id}' not found")
    return _run_with_fallback(project_id, explorer_entry_id, page_info, design_standard, design_direction)


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
