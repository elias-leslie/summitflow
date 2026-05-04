from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class NoteResponse(BaseModel):
    id: str
    project_scope: str
    type: str
    title: str
    content: str
    tags: list[str]
    pinned: bool
    metadata: dict[str, Any]
    created_at: str | None
    updated_at: str | None


class CreateNoteRequest(BaseModel):
    title: str
    content: str = ""
    project_scope: str = "global"
    type: Literal["note", "prompt"] = "note"
    tags: list[str] = []
    pinned: bool = False
    metadata: dict[str, Any] | None = None


class UpdateNoteRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    project_scope: str | None = None
    type: Literal["note", "prompt"] | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    metadata: dict[str, Any] | None = None
