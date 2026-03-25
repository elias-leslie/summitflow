"""Internal workflow helpers for mockup generator.

Contains page design analysis workflow logic and utility helpers."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any
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


def get_design_standard(project_id: str, standards_id: str) -> dict[str, Any] | None:
    """Get design standard by ID."""
    from ...storage.design_standards import get_base_standard, get_project_standard

    if standards_id == "base":
        design_standard = get_base_standard()
    else:
        design_standard = get_project_standard(project_id, standards_id)
    if not design_standard:
        design_standard = get_base_standard()
    return design_standard


def extract_path_from_url(url: str) -> str:
    """Extract path component from a URL."""
    return urlparse(url).path or "/"


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _try_generate_mockup(
    project_id: str,
    screenshot_path: Path,
    mockup_image_path: Path,
    recommendations: str | None,
    page_url: str,
) -> Path:
    """Attempt to generate a mockup image; returns the resulting path."""
    if not recommendations:
        return mockup_image_path
    try:
        result = generate_mockup_image(
            project_id=project_id,
            screenshot_path=screenshot_path,
            recommendations=recommendations,
            output_path=mockup_image_path,
            page_url=page_url,
        )
        if result:
            return Path(result)
    except Exception as e:
        logger.warning("mockup_image_generation_failed", error=str(e))
    return mockup_image_path


def _store_mockup_and_build_result(
    project_id: str, page_url: str, page_path: str,
    screenshot_path: Path, mockup_image_path: Path,
    recommendations: str | None, issues_count: int, generation_time_ms: int,
) -> DesignAnalysisResult:
    """Persist the mockup record and return the final result."""
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


async def run_analyze_page_design(
    project_id: str,
    page_url: str,
    page_path: str | None = None,
) -> DesignAnalysisResult:
    """Analyze a page's design and generate improvement recommendations.

    Workflow: capture screenshot → fetch design rules → vision analysis →
    generate mockup image → store record.
    """
    start_time = time.monotonic()
    if page_path is None:
        page_path = extract_path_from_url(page_url)

    screenshot_id = f"analysis-{int(time.time())}"
    screenshot_dir = MOCKUP_BASE_DIR / project_id / screenshot_id
    screenshot_path = screenshot_dir / "screenshot.png"

    success, error = await capture_page_screenshot(page_url, screenshot_path)
    if not success:
        return DesignAnalysisResult(
            success=False,
            error=f"Screenshot capture failed: {error}",
            generation_time_ms=_elapsed_ms(start_time),
        )

    from ...storage.design_standards import get_effective_rules
    design_rules = get_effective_rules(project_id) or []
    recommendations, issues_count, analysis_error = analyze_screenshot_with_vision(
        project_id, screenshot_path, design_rules, page_url
    )
    if analysis_error:
        return DesignAnalysisResult(
            success=False,
            screenshot_path=str(screenshot_path),
            error=f"Vision analysis failed: {analysis_error}",
            generation_time_ms=_elapsed_ms(start_time),
        )

    mockup_image_path = _try_generate_mockup(
        project_id, screenshot_path, screenshot_dir / "mockup.png", recommendations, page_url
    )
    return _store_mockup_and_build_result(
        project_id, page_url, page_path, screenshot_path,
        mockup_image_path, recommendations, issues_count, _elapsed_ms(start_time),
    )
