"""Utility functions for mockups API."""

from typing import Any

from .mockups_models import MockupResponse


def to_response(mockup: dict[str, Any]) -> MockupResponse:
    """Convert storage dict to response model."""
    return MockupResponse(
        id=mockup["id"],
        project_id=mockup["project_id"],
        mockup_id=mockup["mockup_id"],
        name=mockup["name"],
        description=mockup["description"],
        mockup_type=mockup["mockup_type"],
        file_path=mockup["file_path"],
        content=mockup["content"],
        status=mockup["status"],
        approved_at=mockup["approved_at"],
        approved_by=mockup["approved_by"],
        applied_at=mockup["applied_at"],
        task_id=mockup["task_id"],
        page_path=mockup["page_path"],
        version=mockup["version"],
        parent_mockup_id=mockup["parent_mockup_id"],
        generator=mockup["generator"],
        generation_prompt=mockup["generation_prompt"],
        generation_time_ms=mockup["generation_time_ms"],
        iteration_count=mockup["iteration_count"],
        created_at=mockup["created_at"],
        updated_at=mockup["updated_at"],
    )
