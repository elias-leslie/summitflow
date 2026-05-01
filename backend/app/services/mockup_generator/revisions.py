"""Agent Hub-backed mockup revision generation."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from ...logging_config import get_logger
from ...storage import mockups as mockups_storage
from ..agent_hub_client import get_sync_client

logger = get_logger(__name__)

UI_MOCKUP_DESIGNER_AGENT = "ui-mockup-designer"
_CONTENT_LIMIT = 24000


@dataclass
class MockupRevisionResult:
    """Stored result from rerunning a mockup through Agent Hub."""

    mockup: dict[str, Any]
    agent_slug: str
    model_used: str | None
    provider: str | None
    session_id: str | None
    generation_time_ms: int


class MockupRevisionContentError(RuntimeError):
    """Agent response lacked usable revised mockup content."""


def _extract_json(content: str) -> dict[str, Any]:
    """Extract first JSON object from an Agent Hub response."""
    try:
        decoder = json.JSONDecoder()
        match = re.search(r"\{", content)
        if match:
            parsed, _ = decoder.raw_decode(content[match.start() :])
            if isinstance(parsed, dict):
                return parsed
    except json.JSONDecodeError:
        logger.warning("mockup_revision_json_parse_failed", preview=content[:240])
    return {}


def _clip_content(content: str | None) -> str:
    if not content:
        return ""
    if len(content) <= _CONTENT_LIMIT:
        return content
    return f"{content[:_CONTENT_LIMIT]}\n\n<!-- truncated for model context -->"


def _build_revision_prompt(mockup: dict[str, Any], notes: str) -> str:
    source_content = _clip_content(mockup.get("content"))
    source_kind = "html_or_text" if source_content else "image_or_metadata_only"
    return f"""
Revise one SummitFlow UI design mockup.

Rules:
- Default to the target project's existing design system, color scheme, theme, CSS style, density, spacing, typography, and component conventions.
- Treat user notes as requested changes, not a full redesign unless notes explicitly ask for one.
- Preserve useful structure from the source mockup.
- Return a complete self-contained HTML document when producing visual UI.
- Use inline CSS only. Do not reference external assets, scripts, fonts, CDNs, or network resources.
- Keep interactions static unless simple CSS-only states help communicate intent.
- Do not include markdown.
- Return strict JSON only with keys: name, description, content, change_summary.

Project id: {mockup["project_id"]}
Page path: {mockup.get("page_path") or ""}
Mockup type: {mockup.get("mockup_type") or "page"}
Current name: {mockup.get("name") or ""}
Current description: {mockup.get("description") or ""}
Current version: {mockup.get("version") or 1}
Source kind: {source_kind}

User notes:
{notes.strip()}

Current mockup content:
{source_content or "(No HTML/text content available. Create a faithful HTML mockup from metadata and notes.)"}
""".strip()


def _coerce_revision_payload(parsed: dict[str, Any], fallback: dict[str, Any]) -> dict[str, str]:
    name = str(parsed.get("name") or f"{fallback['name']} revision").strip()
    description = str(
        parsed.get("description")
        or parsed.get("change_summary")
        or fallback.get("description")
        or "Agent-generated mockup revision"
    ).strip()
    content = str(parsed.get("content") or "").strip()
    change_summary = str(parsed.get("change_summary") or description).strip()
    if not content:
        raise MockupRevisionContentError("Agent response did not include revised mockup content")
    return {
        "name": name[:240],
        "description": description,
        "content": content,
        "change_summary": change_summary,
    }


def rerun_mockup(
    project_id: str,
    mockup_id: str,
    notes: str,
) -> MockupRevisionResult:
    """Generate and store a revised mockup using the dedicated Agent Hub agent."""
    source = mockups_storage.get_mockup(project_id, mockup_id)
    if not source:
        raise ValueError("Mockup not found")
    cleaned_notes = notes.strip()
    if not cleaned_notes:
        raise ValueError("Revision notes are required")

    prompt = _build_revision_prompt(source, cleaned_notes)
    start_time = time.monotonic()
    response = get_sync_client().complete(
        agent_slug=UI_MOCKUP_DESIGNER_AGENT,
        messages=[{"role": "user", "content": prompt}],
        project_id=project_id,
        purpose="ui_mockup_revision",
        external_id=mockup_id,
        enable_caching=False,
        use_memory=True,
        memory_group_id=project_id,
    )
    generation_time_ms = int((time.monotonic() - start_time) * 1000)
    payload = _coerce_revision_payload(_extract_json(response.content), source)

    stored = mockups_storage.create_mockup(
        project_id=project_id,
        name=payload["name"],
        description=payload["description"],
        mockup_type=source.get("mockup_type") or "page",
        content=payload["content"],
        task_id=source.get("task_id"),
        page_path=source.get("page_path"),
        parent_mockup_id=source["id"],
        generator=f"agent:{UI_MOCKUP_DESIGNER_AGENT}",
        generation_prompt=cleaned_notes,
        generation_time_ms=generation_time_ms,
    )

    return MockupRevisionResult(
        mockup=stored,
        agent_slug=UI_MOCKUP_DESIGNER_AGENT,
        model_used=response.model,
        provider=response.provider,
        session_id=response.session_id,
        generation_time_ms=generation_time_ms,
    )
