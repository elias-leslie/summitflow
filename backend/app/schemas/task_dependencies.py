"""Task dependency schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DependencyCreate(BaseModel):
    """Request model for creating a dependency."""

    depends_on_task_id: str
    dependency_type: Literal["blocks", "discovered-from"] = "blocks"


class DependencyResponse(BaseModel):
    """Response model for a dependency."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: str
    depends_on_task_id: str
    dependency_type: str
    created_at: datetime | None
    depends_on_title: str | None = None
    depends_on_status: str | None = None
