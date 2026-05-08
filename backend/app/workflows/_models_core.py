"""Core shared workflow input models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

from ._model_constants import DEFAULT_PROJECT_ID


class TaskInput(BaseModel):
    task_id: str
    project_id: str
    manual_dispatch: bool = False


class ProjectInput(BaseModel):
    """Project input for workflows, including cron-triggered ones.

    Hatchet cron triggers may pass None instead of {} as input.
    The model_validator ensures defaults apply in both cases.
    """

    project_id: str = DEFAULT_PROJECT_ID

    @model_validator(mode="before")
    @classmethod
    def _handle_none_input(cls, data: Any) -> Any:
        if data is None:
            return {}
        return data


class EmptyInput(BaseModel):
    pass
