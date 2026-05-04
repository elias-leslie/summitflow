from __future__ import annotations

from pydantic import BaseModel


class ProposalResponse(BaseModel):
    id: str
    note_id: str
    status: str
    original_title: str
    original_content: str
    proposed_title: str | None
    proposed_content: str | None
    error_message: str | None
    created_at: str | None
    completed_at: str | None


class VersionResponse(BaseModel):
    id: str
    note_id: str
    version: int
    title: str
    content: str
    tags: list[str]
    change_source: str
    created_at: str | None


class NotesCapabilitiesResponse(BaseModel):
    title_generation: bool
    formatting: bool
    prompt_refinement: bool


class NotesScopeOptionResponse(BaseModel):
    value: str
    label: str
    known: bool
