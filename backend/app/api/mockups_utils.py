"""Utility functions for mockups API."""

import html
import re
from typing import Any

from .mockups_models import MockupContextResponse, MockupResponse

_MAX_ANNOTATIONS = 20
_MAX_NOTE_CHARS = 500
_MAX_SUMMARY_CHARS = 1800
_MAX_CONTENT_EXCERPT_CHARS = 4000
_NOTE_ATTR_RE = re.compile(
    r"data-sf-mock-note-text=([\"'])(.*?)\1",
    re.IGNORECASE | re.DOTALL,
)
_NOTE_ELEMENT_RE = re.compile(
    r"<[^>]*class=([\"'])[^\"']*sf-mock-note[^\"']*\1[^>]*>(.*?)</[^>]+>",
    re.IGNORECASE | re.DOTALL,
)


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _clip(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _content_note_annotations(content: str | None) -> list[dict[str, Any]]:
    if not content:
        return []
    notes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _NOTE_ATTR_RE.finditer(content):
        note = _clip(html.unescape(match.group(2) or ""), _MAX_NOTE_CHARS)
        if note and note not in seen:
            seen.add(note)
            notes.append({"note": note, "source": "html"})
    for match in _NOTE_ELEMENT_RE.finditer(content):
        note = _clip(
            html.unescape(_strip_tags(match.group(2) or "")),
            _MAX_NOTE_CHARS,
        )
        if note and note not in seen:
            seen.add(note)
            notes.append({"note": note, "source": "html"})
    return notes[:_MAX_ANNOTATIONS]


def _metadata_annotations(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw = metadata.get("annotations")
    if not isinstance(raw, list):
        return []
    annotations: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        note = item.get("note")
        if not isinstance(note, str) or not note.strip():
            continue
        annotations.append(
            {
                "id": item.get("id"),
                "note": _clip(note, _MAX_NOTE_CHARS),
                "element_path": item.get("element_path"),
                "element_label": item.get("element_label"),
                "rect": item.get("rect"),
                "created_at": item.get("created_at"),
                "source": "metadata",
            }
        )
    return annotations[:_MAX_ANNOTATIONS]


def compact_context_for_mockup(
    mockup: dict[str, Any],
    *,
    include_content: bool = False,
) -> MockupContextResponse:
    """Build a compact artifact context. Full HTML is opt-in."""
    raw_metadata = mockup.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    annotations = _metadata_annotations(metadata) or _content_note_annotations(
        mockup.get("content")
    )
    header = f"{mockup['name']} ({mockup['mockup_id']} v{mockup.get('version') or 1})"
    parts = [header]
    if mockup.get("page_path"):
        parts.append(f"page {mockup['page_path']}")
    if mockup.get("task_id"):
        parts.append(f"task {mockup['task_id']}")
    if mockup.get("description"):
        parts.append(_clip(str(mockup["description"]), 260))
    if annotations:
        parts.append(
            "notes: "
            + " | ".join(
                _clip(
                    f"{item.get('element_label') or item.get('element_path') or 'surface'}: "
                    f"{item['note']}",
                    220,
                )
                for item in annotations
            )
        )
    compact_summary = _clip(" - ".join(parts), _MAX_SUMMARY_CHARS)
    content = mockup.get("content") if include_content else None
    content_excerpt = (
        _clip(mockup.get("content") or "", _MAX_CONTENT_EXCERPT_CHARS)
        if mockup.get("content")
        else None
    )
    return MockupContextResponse(
        project_id=mockup["project_id"],
        mockup_id=mockup["mockup_id"],
        name=mockup["name"],
        description=mockup.get("description"),
        version=mockup.get("version") or 1,
        page_path=mockup.get("page_path"),
        task_id=mockup.get("task_id"),
        parent_mockup_id=mockup.get("parent_mockup_id"),
        generator=mockup.get("generator"),
        updated_at=mockup.get("updated_at"),
        annotation_count=len(annotations),
        annotations=annotations,
        compact_summary=compact_summary,
        content_included=include_content,
        content_excerpt=content_excerpt,
        content=content,
    )


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
        metadata=mockup.get("metadata") or {},
        created_at=mockup["created_at"],
        updated_at=mockup["updated_at"],
        rating_average=mockup.get("rating_average", 0.0),
        rating_count=mockup.get("rating_count", 0),
        user_rating=mockup.get("user_rating", 0),
        comment_count=mockup.get("comment_count", 0),
    )
