"""Internal workflow helpers for mockup generator.

Contains page design analysis workflow logic and utility helpers.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from ...logging_config import get_logger
from ...storage import mockups as mockups_storage
from .analysis import (
    analyze_screenshot_with_vision,
    capture_page_screenshot,
    generate_mockup_image,
)
from .models import DesignAnalysisResult
from .storage_helpers import MOCKUP_BASE_DIR

logger = get_logger(__name__)


def get_design_standard(project_id: str, standards_id: str) -> dict | None:
    """Get design standard by ID.

    Args:
        project_id: Project ID
        standards_id: Design standard ID

    Returns:
        Design standard dict or None
    """
    from ..storage.design_standards import get_base_standard, get_project_standard

    if standards_id == "base":
        design_standard = get_base_standard()
    else:
        design_standard = get_project_standard(project_id, standards_id)

    if not design_standard:
        design_standard = get_base_standard()

    return design_standard


def extract_path_from_url(url: str) -> str:
    """Extract path component from a URL.

    Args:
        url: Full URL

    Returns:
        Path component of URL
    """
    parsed = urlparse(url)
    return parsed.path or "/"


async def run_analyze_page_design(
    project_id: str,
    page_url: str,
    page_path: str | None = None,
) -> DesignAnalysisResult:
    """Analyze a page's design and generate improvement recommendations.

    This is the main workflow for mockup generation:
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
    start_time = time.monotonic()

    if page_path is None:
        page_path = extract_path_from_url(page_url)

    # Step 1: Capture screenshot
    screenshot_id = f"analysis-{int(time.time())}"
    screenshot_dir = MOCKUP_BASE_DIR / project_id / screenshot_id
    screenshot_path = screenshot_dir / "screenshot.png"

    success, error = await capture_page_screenshot(page_url, screenshot_path)
    if not success:
        return DesignAnalysisResult(
            success=False,
            error=f"Screenshot capture failed: {error}",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    # Step 2: Get design rules
    from ..storage.design_standards import get_effective_rules

    design_rules = get_effective_rules(project_id) or []

    # Step 3: Analyze with vision
    recommendations, issues_count, analysis_error = analyze_screenshot_with_vision(
        screenshot_path,
        design_rules,
        page_url,
    )

    if analysis_error:
        return DesignAnalysisResult(
            success=False,
            screenshot_path=str(screenshot_path),
            error=f"Vision analysis failed: {analysis_error}",
            generation_time_ms=int((time.monotonic() - start_time) * 1000),
        )

    # Step 4: Generate mockup image showing the improved design
    mockup_image_path = screenshot_dir / "mockup.png"

    if recommendations:
        try:
            mockup_image_path_str = generate_mockup_image(
                screenshot_path=screenshot_path,
                recommendations=recommendations,
                output_path=mockup_image_path,
                page_url=page_url,
            )
            if mockup_image_path_str:
                mockup_image_path = Path(mockup_image_path_str)
        except Exception as e:
            logger.warning("mockup_image_generation_failed", error=str(e))

    # Step 5: Store in mockups table
    generation_time_ms = int((time.monotonic() - start_time) * 1000)
    primary_file = str(mockup_image_path) if mockup_image_path.exists() else str(screenshot_path)

    mockup = mockups_storage.create_mockup(
        project_id=project_id,
        name=f"Design Analysis: {page_path}",
        description=f"Automated design analysis of {page_url}",
        mockup_type="page",
        file_path=primary_file,
        page_path=page_path,
        generator="design-analyzer",
        generation_prompt=recommendations,
        generation_time_ms=generation_time_ms,
    )

    logger.info(
        "page_design_analyzed",
        project_id=project_id,
        page_url=page_url,
        mockup_id=mockup["mockup_id"],
        issues_found=issues_count,
        generation_time_ms=generation_time_ms,
        mockup_image_generated=mockup_image_path.exists(),
    )

    return DesignAnalysisResult(
        success=True,
        mockup_id=mockup["mockup_id"],
        screenshot_path=str(screenshot_path),
        mockup_image_path=(str(mockup_image_path) if mockup_image_path.exists() else None),
        recommendations=recommendations,
        issues_found=issues_count,
        generation_time_ms=generation_time_ms,
    )
