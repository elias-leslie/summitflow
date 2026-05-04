"""Notes API - REST endpoints for cross-project notes and prompts.

This module provides:
- List notes with filtering (project scope, type, tags, search, pinned)
- CRUD operations for notes and prompts
- Tag listing for discovery
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException

from ..logging_config import get_logger
from ..storage import notes as note_store
from ..storage import projects as project_store
from .notes_models import CreateNoteRequest, NoteResponse, UpdateNoteRequest
from .notes_proposal_models import (
    NotesCapabilitiesResponse,
    NotesScopeOptionResponse,
    ProposalResponse,
    VersionResponse,
)

logger = get_logger(__name__)

router = APIRouter(tags=["Notes"])

_EDIT_VERSION_FIELDS = {"title", "content", "tags"}
_EDIT_CHECKPOINT_COOLDOWN = timedelta(minutes=5)


# ============================================================================
# Helpers
# ============================================================================


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt else None


def _get_note_or_404(note_id: str) -> dict[str, Any]:
    note = note_store.get_note(note_id)
    if not note:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    return note


def _note_to_response(note: dict[str, Any]) -> NoteResponse:
    return NoteResponse(
        id=note["id"],
        project_scope=note["project_scope"],
        type=note["type"],
        title=note["title"],
        content=note["content"],
        tags=note.get("tags", []),
        pinned=note["pinned"],
        metadata=note.get("metadata", {}),
        created_at=_iso(note.get("created_at")),
        updated_at=_iso(note.get("updated_at")),
    )


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
        created_at=_iso(p.get("created_at")),
        completed_at=_iso(p.get("completed_at")),
    )


def _version_to_response(v: dict[str, Any]) -> VersionResponse:
    return VersionResponse(
        id=v["id"],
        note_id=v["note_id"],
        version=v["version"],
        title=v["title"],
        content=v["content"],
        tags=v.get("tags", []),
        change_source=v["change_source"],
        created_at=_iso(v.get("created_at")),
    )


def _normalize_tags(tags: list[str] | None) -> list[str]:
    return tags or []


def _build_scope_options(
    projects: list[dict[str, Any]],
    observed_scopes: list[str],
) -> list[NotesScopeOptionResponse]:
    options = [
        NotesScopeOptionResponse(value="global", label="Global", known=True),
    ]
    seen = {"global"}

    for project in sorted(projects, key=lambda item: str(item.get("name") or item.get("id") or "").lower()):
        project_id = str(project.get("id") or "").strip()
        if not project_id or project_id in seen:
            continue
        label = str(project.get("name") or project_id).strip() or project_id
        seen.add(project_id)
        options.append(
            NotesScopeOptionResponse(value=project_id, label=label, known=True)
        )

    for scope in observed_scopes:
        normalized = str(scope or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        options.append(
            NotesScopeOptionResponse(
                value=normalized,
                label=normalized,
                known=False,
            )
        )

    return options


def _note_state_matches(
    snapshot: dict[str, Any], *, title: str, content: str, tags: list[str] | None
) -> bool:
    return (
        snapshot["title"] == title
        and snapshot["content"] == content
        and _normalize_tags(snapshot.get("tags")) == _normalize_tags(tags)
    )


def _has_meaningful_note_changes(existing: dict[str, Any], fields: dict[str, Any]) -> bool:
    if not _EDIT_VERSION_FIELDS.intersection(fields):
        return False
    next_title = fields.get("title", existing["title"])
    next_content = fields.get("content", existing["content"])
    next_tags = fields.get("tags", existing.get("tags", []))
    return not _note_state_matches(
        existing,
        title=next_title,
        content=next_content,
        tags=next_tags,
    )


def _within_edit_checkpoint_window(created_at: Any) -> bool:
    if not isinstance(created_at, datetime):
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at >= datetime.now(tz=UTC) - _EDIT_CHECKPOINT_COOLDOWN


def _maybe_create_edit_checkpoint(note_id: str, existing: dict[str, Any], fields: dict[str, Any]) -> None:
    if not _has_meaningful_note_changes(existing, fields):
        return

    from ..storage import note_versions as versions

    latest = versions.get_latest_version(note_id)
    if latest and _note_state_matches(
        latest,
        title=existing["title"],
        content=existing["content"],
        tags=existing.get("tags", []),
    ):
        return
    if latest and _within_edit_checkpoint_window(latest.get("created_at")):
        return

    versions.create_version(
        note_id=note_id,
        title=existing["title"],
        content=existing["content"],
        tags=existing.get("tags", []),
        change_source="edit_checkpoint",
    )


# ============================================================================
# CRUD Endpoints
# ============================================================================


@router.get("/notes/capabilities", response_model=NotesCapabilitiesResponse)
async def get_capabilities() -> NotesCapabilitiesResponse:
    """Return Notes feature capabilities for this backend."""
    return NotesCapabilitiesResponse(
        title_generation=True,
        formatting=True,
        prompt_refinement=True,
    )


@router.get("/notes/scopes", response_model=list[NotesScopeOptionResponse])
async def get_scopes() -> list[NotesScopeOptionResponse]:
    """Return canonical note scopes from the project registry plus Global."""
    return _build_scope_options(
        project_store.list_projects(),
        note_store.list_project_scopes(),
    )


@router.get("/notes/tags")
async def get_tags(project_scope: str | None = None) -> dict[str, Any]:
    """Get all distinct tags, optionally filtered by project scope."""
    return {"tags": note_store.list_tags(project_scope)}


@router.get("/notes")
async def list_notes(
    project_scope: str | None = None,
    type: Literal["note", "prompt"] | None = None,
    tag: list[str] | None = None,
    search: str | None = None,
    pinned: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List notes with optional filters."""
    items = note_store.list_notes(
        project_scope=project_scope, note_type=type, tags=tag,
        search=search, pinned=pinned, limit=limit, offset=offset,
    )
    total = note_store.count_notes(
        project_scope=project_scope, note_type=type, tags=tag,
        search=search, pinned=pinned,
    )
    return {"items": [_note_to_response(n) for n in items], "total": total}


@router.get("/notes/{note_id}", response_model=NoteResponse)
async def get_note(note_id: str) -> NoteResponse:
    """Get a single note by ID."""
    return _note_to_response(_get_note_or_404(note_id))


@router.post("/notes", response_model=NoteResponse, status_code=201)
async def create_note(request: CreateNoteRequest) -> NoteResponse:
    """Create a new note or prompt."""
    note = note_store.create_note(
        title=request.title, content=request.content,
        project_scope=request.project_scope, note_type=request.type,
        tags=request.tags, pinned=request.pinned, metadata=request.metadata,
    )
    return _note_to_response(note)


@router.patch("/notes/{note_id}", response_model=NoteResponse)
async def update_note(note_id: str, request: UpdateNoteRequest) -> NoteResponse:
    """Update a note (partial update)."""
    existing = _get_note_or_404(note_id)
    fields = {k: v for k, v in request.model_dump().items() if v is not None}
    _maybe_create_edit_checkpoint(note_id, existing, fields)
    note = note_store.update_note(note_id, **fields)
    if not note:
        raise HTTPException(status_code=500, detail="Failed to update note")
    return _note_to_response(note)


@router.delete("/notes/{note_id}")
async def delete_note(note_id: str) -> dict[str, Any]:
    """Delete a note."""
    _get_note_or_404(note_id)
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
        return {"title": str(data.get("title", "")).strip()[:120], "content": str(data.get("content", "")).strip()}
    except _json.JSONDecodeError:
        return {"title": "", "content": ""}


def _extract_title(raw: str) -> str:
    """Extract a title from note-titler agent output."""
    cleaned = _CODE_FENCE_RE.sub("", _TAG_RE.sub("", raw)).strip()
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


async def _run_agent_task(
    proposal_id: str, agent_slug: str, prompt: str, parse_fn: str,
    fallback_title: str, fallback_content: str,
) -> None:
    """Async task: call agent and write result to DB."""
    from ..services.agent_hub_client import AgentHubLLMClient
    from ..storage import note_format_proposals as proposals

    try:
        client = AgentHubLLMClient(agent_slug=agent_slug, use_memory=(agent_slug != "note-formatter"))
        raw = await asyncio.to_thread(
            lambda: client.generate(prompt, temperature=0.3, purpose="notes").content
        )
        if parse_fn == "format":
            parsed = _parse_format_response(raw)
            proposed_title = parsed["title"] or fallback_title or "Untitled"
            proposed_content = parsed["content"] or fallback_content
        else:
            proposed_title = ""
            proposed_content = _CODE_FENCE_RE.sub("", _TAG_RE.sub("", raw)).strip()
        proposals.complete_proposal(proposal_id, proposed_title, proposed_content)
        logger.info("Proposal %s completed (agent=%s)", proposal_id, agent_slug)
    except Exception as e:
        logger.warning("Proposal %s failed (agent=%s): %s", proposal_id, agent_slug, e)
        proposals.fail_proposal(proposal_id, str(e))


def _run_agent_in_background(
    proposal_id: str, agent_slug: str, prompt: str, parse_fn: str,
    fallback_title: str = "", fallback_content: str = "",
) -> None:
    """Fire-and-forget: schedule _run_agent_task on the running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(
        _run_agent_task(proposal_id, agent_slug, prompt, parse_fn, fallback_title, fallback_content)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _accept_proposal(proposal_id: str) -> None:
    """Apply an accepted format proposal: snapshot, update, record post-state version."""
    from ..storage import note_versions as versions
    from ..storage.connection import get_cursor

    with get_cursor() as cur:
        cur.execute(
            "SELECT note_id, proposed_title, proposed_content FROM note_format_proposals WHERE id = %s",
            (proposal_id,),
        )
        row = cur.fetchone()
    if not row:
        return
    note_id, proposed_title, proposed_content = row
    existing = note_store.get_note(note_id)
    if existing:
        versions.create_version(
            note_id=note_id, title=existing["title"], content=existing["content"],
            tags=existing.get("tags", []), change_source="pre_format",
        )
    if proposed_title or proposed_content:
        updates = {k: v for k, v in [("title", proposed_title), ("content", proposed_content)] if v}
        note_store.update_note(note_id, **updates)
        versions.create_version(
            note_id=note_id,
            title=proposed_title or (existing["title"] if existing else ""),
            content=proposed_content or (existing["content"] if existing else ""),
            tags=existing.get("tags", []) if existing else [],
            change_source="format_accept",
        )


@router.post("/notes/format", response_model=ProposalResponse, status_code=202)
async def format_note(
    note_id: str = Body(...),
    content: str = Body(...),
    current_title: str = Body(""),
) -> ProposalResponse:
    """Start a background format job. Returns the proposal immediately with status='pending'."""
    if len(content.strip()) < 20:
        raise HTTPException(status_code=400, detail="Content too short to format")
    from ..storage import note_format_proposals as proposals

    proposal = proposals.create_proposal(note_id, current_title, content)
    _run_agent_in_background(proposal["id"], "note-formatter", content[:3000], "format",
                             fallback_title=current_title, fallback_content=content)
    return _proposal_to_response(proposal)


@router.post("/notes/refine-prompt", response_model=ProposalResponse, status_code=202)
async def refine_prompt(
    note_id: str = Body(...),
    current_content: str = Body(""),
    instruction: str = Body(...),
) -> ProposalResponse:
    """Start a background prompt refinement. Returns the proposal immediately."""
    if not instruction.strip():
        raise HTTPException(status_code=400, detail="Instruction is required")
    from ..storage import note_format_proposals as proposals

    prompt = (
        f"CURRENT PROMPT:\n{current_content}\n\nREFINEMENT:\n{instruction}"
        if current_content.strip() else instruction
    )
    proposal = proposals.create_proposal(note_id, "", current_content)
    _run_agent_in_background(proposal["id"], "prompt-builder", prompt, "refine")
    return _proposal_to_response(proposal)


@router.get("/notes/{note_id}/format-proposal", response_model=ProposalResponse | None)
async def get_format_proposal(note_id: str) -> ProposalResponse | None:
    """Get the latest pending or complete format proposal for a note."""
    from ..storage import note_format_proposals as proposals

    p = proposals.get_latest_proposal(note_id)
    return _proposal_to_response(p) if p else None


@router.post("/notes/format-proposals/{proposal_id}/resolve")
async def resolve_format_proposal(
    proposal_id: str, action: str = Body(..., embed=True),
) -> dict[str, Any]:
    """Accept or discard a format proposal."""
    from ..storage import note_format_proposals as proposals

    if action not in ("accept", "discard"):
        raise HTTPException(status_code=400, detail="action must be 'accept' or 'discard'")
    if action == "accept":
        _accept_proposal(proposal_id)
    status = "accepted" if action == "accept" else "discarded"
    proposals.resolve_proposal(proposal_id, status)
    return {"resolved": True, "status": status}


@router.post("/notes/generate-title")
async def generate_title(content: str = Body(..., embed=True)) -> dict[str, Any]:
    """Generate a title only (no content formatting). Uses the fast note-titler agent."""
    if len(content.strip()) < 20:
        raise HTTPException(status_code=400, detail="Content too short")
    try:
        from ..services.agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(agent_slug="note-titler", use_memory=False)
        raw = await asyncio.to_thread(
            lambda: client.generate(content[:1000], temperature=0.3, purpose="note_title").content
        )
        title = _extract_title(raw)
        if not title:
            raise HTTPException(status_code=502, detail="Title generation returned empty result")
        return {"title": title}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Title generation failed: %s", e)
        raise HTTPException(status_code=502, detail="Title generation unavailable") from e


# ============================================================================
# Note Versions
# ============================================================================


@router.get("/notes/{note_id}/versions", response_model=list[VersionResponse])
async def list_versions(note_id: str) -> list[VersionResponse]:
    """List version history for a note."""
    from ..storage import note_versions as versions

    _get_note_or_404(note_id)
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

    existing = _get_note_or_404(note_id)
    v = versions.create_version(
        note_id=note_id, title=existing["title"], content=existing["content"],
        tags=existing.get("tags", []), change_source="manual_snapshot",
    )
    return _version_to_response(v)


@router.post("/notes/{note_id}/revert/{version_id}", response_model=NoteResponse)
async def revert_to_version(note_id: str, version_id: str) -> NoteResponse:
    """Revert a note to a previous version. Creates a version snapshot before reverting."""
    from ..storage import note_versions as versions

    existing = _get_note_or_404(note_id)
    v = versions.get_version(version_id)
    if not v or v["note_id"] != note_id:
        raise HTTPException(status_code=404, detail=f"Version {version_id} not found for note {note_id}")

    versions.create_version(
        note_id=note_id, title=existing["title"], content=existing["content"],
        tags=existing.get("tags", []), change_source="pre_revert",
    )
    note = note_store.update_note(note_id, title=v["title"], content=v["content"], tags=v["tags"])
    if not note:
        raise HTTPException(status_code=500, detail="Failed to revert note")
    versions.create_version(
        note_id=note_id, title=v["title"], content=v["content"],
        tags=v["tags"], change_source="revert",
    )
    return _note_to_response(note)
