"""Pydantic models for Agent Hub observability endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentHubEvent(BaseModel):
    """Single event from Agent Hub session."""

    id: str
    session_id: str | None = None
    session_index: int = 0
    turn: int
    sequence: int
    event_type: str
    role: str | None = None
    content: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    tokens: int | None = None
    duration_ms: int | None = None
    model_used: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    created_at: str


class AgentHubLiveActivity(BaseModel):
    """Live execution state mirrored from Agent Hub session responses."""

    phase: str
    status: str
    summary: str | None = None
    health: str
    stalled: bool = False
    stall_reason: str | None = None
    quiet_for_seconds: int | None = None
    current_tool_name: str | None = None
    last_tool_name: str | None = None
    last_read_path: str | None = None
    last_write_path: str | None = None
    last_command: str | None = None
    last_validation_command: str | None = None
    last_command_exit_code: int | None = None
    outstanding_tool_calls: int = 0
    tool_calls_count: int = 0
    termination_reason: str | None = None
    files_touched: list[str] = Field(default_factory=list)


class AgentHubSessionSummary(BaseModel):
    """Task-linked Agent Hub session summary."""

    id: str
    status: str
    agent_slug: str | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    requested_provider: str | None = None
    effective_provider: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    updated_at: str
    live_activity: AgentHubLiveActivity | None = None


class AgentHubEventsResponse(BaseModel):
    """Response containing Agent Hub events for a task."""

    task_id: str
    session_ids: list[str]
    sessions: list[AgentHubSessionSummary]
    events: list[AgentHubEvent]
    total: int
    max_turn: int
