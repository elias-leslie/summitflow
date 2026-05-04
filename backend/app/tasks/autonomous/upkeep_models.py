"""Internal data models for routine upkeep."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .upkeep_constants import COMPLEXITY_SIMPLE, SOURCE_FEEDBACK, SOURCE_QUALITY, SOURCE_REFACTORS


class SourceRunResult(BaseModel):
    payload: Any = None
    error: str | None = None


class CreatedSignalTask(BaseModel):
    task_id: str
    source_key: str


class SignalTaskSpec(BaseModel):
    source_key: str
    signal_type: str
    title: str
    description: str
    priority: int
    task_type: str
    subtask_description: str
    complexity: str = COMPLEXITY_SIMPLE
    files_to_modify: list[str] | None = None
    source_context: dict[str, Any] | None = None


class RunAccumulator(BaseModel):
    source_payloads: dict[str, Any] = Field(
        default_factory=lambda: {
            SOURCE_REFACTORS: {},
            SOURCE_QUALITY: {"created_task_ids": []},
            SOURCE_FEEDBACK: {"created_task_ids": []},
        }
    )
    source_errors: dict[str, str] = Field(default_factory=dict)
    created_task_ids: list[str] = Field(default_factory=list)
    refactor_created: int = 0


class RunOutcome(BaseModel):
    source_payloads: dict[str, Any]
    source_errors: dict[str, str]
    created_task_ids: list[str]
