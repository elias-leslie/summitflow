"""Pydantic models for mockups API."""

from pydantic import BaseModel


class MockupCreate(BaseModel):
    """Request to create a mockup."""

    name: str
    description: str | None = None
    mockup_type: str = "component"
    file_path: str | None = None
    content: str | None = None
    task_id: str | None = None
    page_path: str | None = None
    parent_mockup_id: int | None = None
    generator: str | None = None
    generation_prompt: str | None = None
    generation_time_ms: int | None = None


class MockupUpdate(BaseModel):
    """Request to update a mockup."""

    name: str | None = None
    description: str | None = None
    file_path: str | None = None
    content: str | None = None
    page_path: str | None = None


class MockupStatusUpdate(BaseModel):
    """Request to update mockup status."""

    status: str
    approved_by: str | None = None


class MockupResponse(BaseModel):
    """Response model for a mockup."""

    id: int
    project_id: str
    mockup_id: str
    name: str
    description: str | None
    mockup_type: str
    file_path: str | None
    content: str | None
    status: str
    approved_at: str | None
    approved_by: str | None
    applied_at: str | None
    task_id: str | None
    page_path: str | None
    version: int
    parent_mockup_id: int | None
    generator: str | None
    generation_prompt: str | None
    generation_time_ms: int | None
    iteration_count: int
    created_at: str | None
    updated_at: str | None


class MockupListResponse(BaseModel):
    """Response for mockup list endpoint."""

    items: list[MockupResponse]
    total: int
    limit: int
    offset: int


class MockupStatsResponse(BaseModel):
    """Response for mockup statistics."""

    total: int
    by_status: dict[str, int]
    unique_generators: int
    avg_generation_time_ms: float | None


class AnalyzePageRequest(BaseModel):
    """Request to analyze a page's design."""

    page_url: str
    page_path: str | None = None


class AnalyzePageResponse(BaseModel):
    """Response from page design analysis."""

    success: bool
    mockup_id: str | None = None
    screenshot_path: str | None = None
    mockup_image_path: str | None = None
    recommendations: str | None = None
    issues_found: int = 0
    error: str | None = None
    generation_time_ms: int = 0


class RerunMockupRequest(BaseModel):
    """Request to create an Agent Hub-generated mockup revision."""

    notes: str


class RerunMockupResponse(BaseModel):
    """Response from Agent Hub mockup revision generation."""

    success: bool
    mockup: MockupResponse
    agent_slug: str
    model_used: str | None = None
    provider: str | None = None
    session_id: str | None = None
    generation_time_ms: int = 0
