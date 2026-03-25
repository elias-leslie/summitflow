"""Notes API - REST endpoints for cross-project notes and prompts.

This module provides:
- List notes with filtering (project scope, type, tags, search, pinned)
- CRUD operations for notes and prompts
- Tag listing for discovery
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..logging_config import get_logger
from ..storage import notes as note_store

logger = get_logger(__name__)

router = APIRouter(tags=["Notes"])


# ============================================================================
# Request/Response Models
# ============================================================================


class NoteResponse(BaseModel):
    """Note response model."""

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


class NoteListResponse(BaseModel):
    """Response for listing notes."""

    items: list[NoteResponse]
    total: int


class CreateNoteRequest(BaseModel):
    """Request to create a note."""

    title: str
    content: str = ""
    project_scope: str = "global"
    type: Literal["note", "prompt"] = "note"
    tags: list[str] = []
    pinned: bool = False
    metadata: dict[str, Any] | None = None


class UpdateNoteRequest(BaseModel):
    """Request to update a note (partial)."""

    title: str | None = None
    content: str | None = None
    project_scope: str | None = None
    type: Literal["note", "prompt"] | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    metadata: dict[str, Any] | None = None


class TagListResponse(BaseModel):
    """Response for listing tags."""

    tags: list[str]


# ============================================================================
# Helpers
# ============================================================================


def _note_to_response(note: dict[str, Any]) -> NoteResponse:
    """Convert storage note dict to API response."""
    return NoteResponse(
        id=note["id"],
        project_scope=note["project_scope"],
        type=note["type"],
        title=note["title"],
        content=note["content"],
        tags=note.get("tags", []),
        pinned=note["pinned"],
        metadata=note.get("metadata", {}),
        created_at=note["created_at"].isoformat() if note.get("created_at") else None,
        updated_at=note["updated_at"].isoformat() if note.get("updated_at") else None,
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/notes/tags", response_model=TagListResponse)
async def get_tags(
    project_scope: str | None = None,
) -> TagListResponse:
    """Get all distinct tags, optionally filtered by project scope."""
    tags = note_store.list_tags(project_scope)
    return TagListResponse(tags=tags)


@router.get("/notes", response_model=NoteListResponse)
async def list_notes(
    project_scope: str | None = None,
    type: Literal["note", "prompt"] | None = None,
    tag: list[str] | None = None,
    search: str | None = None,
    pinned: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> NoteListResponse:
    """List notes with optional filters."""
    items = note_store.list_notes(
        project_scope=project_scope,
        note_type=type,
        tags=tag,
        search=search,
        pinned=pinned,
        limit=limit,
        offset=offset,
    )
    total = note_store.count_notes(
        project_scope=project_scope,
        note_type=type,
        tags=tag,
        search=search,
        pinned=pinned,
    )
    return NoteListResponse(
        items=[_note_to_response(n) for n in items],
        total=total,
    )


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(note_id: str) -> NoteResponse:
    """Get a single note by ID."""
    note = note_store.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    return _note_to_response(note)


@router.post("/notes", response_model=NoteResponse, status_code=201)
async def create_note(request: CreateNoteRequest) -> NoteResponse:
    """Create a new note or prompt."""
    note = note_store.create_note(
        title=request.title,
        content=request.content,
        project_scope=request.project_scope,
        note_type=request.type,
        tags=request.tags,
        pinned=request.pinned,
        metadata=request.metadata,
    )
    return _note_to_response(note)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, request: UpdateNoteRequest) -> NoteResponse:
    """Update a note (partial update)."""
    existing = note_store.get_note(note_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")

    fields: dict[str, Any] = {}
    if request.title is not None:
        fields["title"] = request.title
    if request.content is not None:
        fields["content"] = request.content
    if request.project_scope is not None:
        fields["project_scope"] = request.project_scope
    if request.type is not None:
        fields["type"] = request.type
    if request.tags is not None:
        fields["tags"] = request.tags
    if request.pinned is not None:
        fields["pinned"] = request.pinned
    if request.metadata is not None:
        fields["metadata"] = request.metadata

    note = note_store.update_note(note_id, **fields)
    if not note:
        raise HTTPException(status_code=500, detail="Failed to update note")
    return _note_to_response(note)


@router.delete("/notes/{note_id}", response_model=dict[str, Any])
async def delete_note(note_id: str) -> dict[str, Any]:
    """Delete a note."""
    existing = note_store.get_note(note_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    if not note_store.delete_note(note_id):
        raise HTTPException(status_code=500, detail="Failed to delete note")
    return {"deleted": True, "id": note_id}


# ============================================================================
# Note Formatting (background, persisted)
# ============================================================================

_TAG_RE = re.compile(r"\[\[[^\]]*\]\]")
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?|\n?```\s*$", re.MULTILINE)
_TITLE_PREFIX_RE = re.compile(r"^TITLE:\s*", re.IGNORECASE)

_background_tasks: set[asyncio.Task[None]] = set()


def _parse_format_response(raw: str) -> dict[str, str]:
    """Parse the formatter agent's JSON response, stripping noise."""
    import json as _json

    cleaned = _TAG_RE.sub("", raw).strip()
    cleaned = _CODE_FENCE_RE.sub("", cleaned).strip()
    try:
        data = _json.loads(cleaned)
        title = str(data.get("title", "")).strip()[:120]
        content = str(data.get("content", "")).strip()
        return {"title": title, "content": content}
    except _json.JSONDecodeError:
        return {"title": "", "content": ""}


def _extract_title(raw: str) -> str:
    """Extract a title from note-titler agent output."""
    cleaned = _TAG_RE.sub("", raw).strip()
    cleaned = _CODE_FENCE_RE.sub("", cleaned).strip()
    for line in cleaned.splitlines():
        line = line.strip()
        m = _TITLE_PREFIX_RE.match(line)
        if m:
            return m.string[m.end():].strip().strip('"').strip("'").strip("`")[:120]
    candidates = [
        ln.strip().strip('"').strip("'").strip("`").strip("#").strip("*").strip()
        for ln in cleaned.splitlines()
        if 5 < len(ln.strip()) < 80
    ]
    if candidates:
        return str(min(candidates, key=len))[:120]
    return ""


# ── Background format task ──


def _run_agent_in_background(
    proposal_id: str, agent_slug: str, prompt: str, parse_fn: str,
    fallback_title: str = "", fallback_content: str = "",
) -> None:
    """Fire-and-forget: call an agent, write result to DB."""
    from ..storage import note_format_proposals as proposals

    async def _do_call() -> None:
        try:
            from ..services.agent_hub_client import AgentHubLLMClient

            client = AgentHubLLMClient(agent_slug=agent_slug, use_memory=(agent_slug != "note-formatter"))

            def _call() -> str:
                resp = client.generate(prompt, temperature=0.3, purpose="notes")
                return resp.content

            raw = await asyncio.to_thread(_call)
            cleaned = _CODE_FENCE_RE.sub("", _TAG_RE.sub("", raw)).strip()

            if parse_fn == "format":
                parsed = _parse_format_response(raw)
                proposed_title = parsed["title"] or fallback_title or "Untitled"
                proposed_content = parsed["content"] or fallback_content
            else:
                # refine: raw output is the full prompt text
                proposed_title = ""
                proposed_content = cleaned

            proposals.complete_proposal(proposal_id, proposed_title, proposed_content)
            logger.info("Proposal %s completed (agent=%s)", proposal_id, agent_slug)
        except Exception as e:
            logger.warning("Proposal %s failed (agent=%s): %s", proposal_id, agent_slug, e)
            proposals.fail_proposal(proposal_id, str(e))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_do_call())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ── Format endpoints ──


class FormatNoteRequest(BaseModel):
    note_id: str
    content: str
    current_title: str = ""


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


def _proposal_to_response(p: dict[str, Any]) -> ProposalResponse:
    return ProposalResponse(
        id=p["id"],
        note_id=p["note_id"],
        status=p["status"],
        original_title=p["original_title"],
        original_content=p["original_content"],
        proposed_title=p.get("proposed_title"),
        proposed_content=p.get("proposed_content"),
        error_message=p.get("error_message"),
        created_at=p["created_at"].isoformat() if p.get("created_at") else None,
        completed_at=p["completed_at"].isoformat() if p.get("completed_at") else None,
    )


@router.post("/notes/format", response_model=ProposalResponse, status_code=202)
async def format_note(request: FormatNoteRequest) -> ProposalResponse:
    """Start a background format job. Returns the proposal immediately with status='pending'."""
    if len(request.content.strip()) < 20:
        raise HTTPException(status_code=400, detail="Content too short to format")

    from ..storage import note_format_proposals as proposals

    proposal = proposals.create_proposal(request.note_id, request.current_title, request.content)
    _run_agent_in_background(
        proposal["id"], "note-formatter", request.content[:3000], "format",
        fallback_title=request.current_title, fallback_content=request.content,
    )
    return _proposal_to_response(proposal)


class RefinePromptRequest(BaseModel):
    note_id: str
    current_content: str = ""
    instruction: str


@router.post("/notes/refine-prompt", response_model=ProposalResponse, status_code=202)
async def refine_prompt(request: RefinePromptRequest) -> ProposalResponse:
    """Start a background prompt refinement. Returns the proposal immediately."""
    if not request.instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction is required")

    from ..storage import note_format_proposals as proposals

    prompt = f"CURRENT PROMPT:\n{request.current_content}\n\nREFINEMENT:\n{request.instruction}" if request.current_content.strip() else request.instruction
    proposal = proposals.create_proposal(request.note_id, "", request.current_content)
    _run_agent_in_background(proposal["id"], "prompt-builder", prompt, "refine")
    return _proposal_to_response(proposal)


@router.get("/notes/{note_id}/format-proposal", response_model=ProposalResponse | None)
async def get_format_proposal(note_id: str) -> ProposalResponse | None:
    """Get the latest pending or complete format proposal for a note."""
    from ..storage import note_format_proposals as proposals

    p = proposals.get_latest_proposal(note_id)
    if not p:
        return None
    return _proposal_to_response(p)


class ResolveProposalRequest(BaseModel):
    action: str  # "accept" or "discard"


@router.post("/notes/format-proposals/{proposal_id}/resolve")
async def resolve_format_proposal(proposal_id: str, request: ResolveProposalRequest) -> dict[str, Any]:
    """Accept or discard a format proposal."""
    from ..storage import note_format_proposals as proposals

    if request.action not in ("accept", "discard"):
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'discard'")

    if request.action == "accept":
        from ..storage import note_versions as versions
        from ..storage.connection import get_cursor

        with get_cursor() as cur:
            cur.execute(
                "SELECT note_id, proposed_title, proposed_content FROM note_format_proposals WHERE id = %s",
                (proposal_id,),
            )
            row = cur.fetchone()
        if row:
            note_id, proposed_title, proposed_content = row
            # Snapshot current state before applying format
            existing = note_store.get_note(note_id)
            if existing:
                versions.create_version(
                    note_id=note_id,
                    title=existing["title"],
                    content=existing["content"],
                    tags=existing.get("tags", []),
                    change_source="pre_format",
                )
            # Apply the formatted version
            if proposed_title or proposed_content:
                updates: dict[str, Any] = {}
                if proposed_title:
                    updates["title"] = proposed_title
                if proposed_content:
                    updates["content"] = proposed_content
                note_store.update_note(note_id, **updates)
                # Record the format as a version
                versions.create_version(
                    note_id=note_id,
                    title=proposed_title or (existing["title"] if existing else ""),
                    content=proposed_content or (existing["content"] if existing else ""),
                    tags=existing.get("tags", []) if existing else [],
                    change_source="format_accept",
                )

    status = "accepted" if request.action == "accept" else "discarded"
    proposals.resolve_proposal(proposal_id, status)
    return {"resolved": True, "status": status}


# ── Title-only generation ──


class GenerateTitleRequest(BaseModel):
    content: str


class GenerateTitleResponse(BaseModel):
    title: str


@router.post("/notes/generate-title", response_model=GenerateTitleResponse)
async def generate_title(request: GenerateTitleRequest) -> GenerateTitleResponse:
    """Generate a title only (no content formatting). Uses the fast note-titler agent."""
    if len(request.content.strip()) < 20:
        raise HTTPException(status_code=400, detail="Content too short")

    try:
        from ..services.agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(agent_slug="note-titler", use_memory=False)

        def _call() -> str:
            return client.generate(request.content[:1000], temperature=0.3, purpose="note_title").content

        raw = await asyncio.to_thread(_call)
        title = _extract_title(raw)
        if not title:
            raise HTTPException(status_code=502, detail="Title generation returned empty result")
        return GenerateTitleResponse(title=title)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Title generation failed: %s", e)
        raise HTTPException(status_code=502, detail="Title generation unavailable") from e


# ============================================================================
# Note Versions
# ============================================================================


class VersionResponse(BaseModel):
    id: str
    note_id: str
    version: int
    title: str
    content: str
    tags: list[str]
    change_source: str
    created_at: str | None


def _version_to_response(v: dict[str, Any]) -> VersionResponse:
    return VersionResponse(
        id=v["id"],
        note_id=v["note_id"],
        version=v["version"],
        title=v["title"],
        content=v["content"],
        tags=v.get("tags", []),
        change_source=v["change_source"],
        created_at=v["created_at"].isoformat() if v.get("created_at") else None,
    )


@router.get("/notes/{note_id}/versions", response_model=list[VersionResponse])
async def list_versions(note_id: str) -> list[VersionResponse]:
    """List version history for a note."""
    from ..storage import note_versions as versions

    existing = note_store.get_note(note_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    return [_version_to_response(v) for v in versions.list_versions(note_id)]


@router.get("/notes/versions/{version_id}", response_model=VersionResponse)
async def get_version(version_id: str) -> VersionResponse:
    """Get a specific version."""
    from ..storage import note_versions as versions

    v = versions.get_version(version_id)
    if not v:
        raise HTTPException(status_code=404, detail=f"Version {version_id} not found")
    return _version_to_response(v)


@router.post("/notes/{note_id}/versions", response_model=VersionResponse, status_code=201)
async def create_version_endpoint(note_id: str) -> VersionResponse:
    """Manually snapshot the current state of a note."""
    from ..storage import note_versions as versions

    existing = note_store.get_note(note_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    v = versions.create_version(
        note_id=note_id,
        title=existing["title"],
        content=existing["content"],
        tags=existing.get("tags", []),
        change_source="manual_snapshot",
    )
    return _version_to_response(v)


@router.post("/notes/{note_id}/revert/{version_id}", response_model=NoteResponse)
async def revert_to_version(note_id: str, version_id: str) -> NoteResponse:
    """Revert a note to a previous version. Creates a version snapshot before reverting."""
    from ..storage import note_versions as versions

    existing = note_store.get_note(note_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    v = versions.get_version(version_id)
    if not v or v["note_id"] != note_id:
        raise HTTPException(status_code=404, detail=f"Version {version_id} not found for note {note_id}")

    # Snapshot current state before reverting
    versions.create_version(
        note_id=note_id,
        title=existing["title"],
        content=existing["content"],
        tags=existing.get("tags", []),
        change_source="pre_revert",
    )

    # Apply the old version
    note = note_store.update_note(
        note_id,
        title=v["title"],
        content=v["content"],
        tags=v["tags"],
    )
    if not note:
        raise HTTPException(status_code=500, detail="Failed to revert note")

    # Record the revert as a version too
    versions.create_version(
        note_id=note_id,
        title=v["title"],
        content=v["content"],
        tags=v["tags"],
        change_source="revert",
    )

    return _note_to_response(note)
