"""Data models for mockup generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MockupResult:
    """Result of mockup generation."""

    success: bool
    mockup_id: str | None = None
    db_id: int | None = None
    image_path: str | None = None
    error: str | None = None
    generator: str | None = None
    generation_time_ms: int = 0


@dataclass
class DesignAnalysisResult:
    """Result of page design analysis."""

    success: bool
    mockup_id: str | None = None
    screenshot_path: str | None = None
    mockup_image_path: str | None = None
    recommendations: str | None = None
    issues_found: int = 0
    error: str | None = None
    generation_time_ms: int = 0


__all__ = ["DesignAnalysisResult", "MockupResult"]
