"""Tests for session events memory summaries."""

from __future__ import annotations

from cli.commands.session_events_formatter import format_event
from cli.commands.session_events_formatter import (
    _format_memory_event_content,
    _selected_refs_from_memory_inject,
)


class TestSessionEventsFormatter:
    def test_memory_inject_summary_uses_reference_split_counts(self) -> None:
        event = {
            "event_type": "memory_inject",
            "tool_input": {
                "count": 57,
                "reference_selected_count": 3,
                "reference_index_count": 29,
            },
        }

        content = _format_memory_event_content(event, verbose=False)

        assert content == "loaded=57 refs:selected=3 index=29"

    def test_memory_cite_summary_shows_selected_reference_hits(self) -> None:
        event = {
            "event_type": "memory_cite",
            "tool_input": {
                "uuids": ["ref-1", "mandate-1", "ref-2"],
            },
        }

        content = _format_memory_event_content(
            event,
            verbose=False,
            selected_reference_uuids={"ref-1", "ref-2", "ref-3"},
        )

        assert content == "cited=3 selected_cited=2/3"

    def test_selected_refs_from_memory_inject_reads_uuid_list(self) -> None:
        event = {
            "event_type": "memory_inject",
            "tool_input": {
                "reference_selected_uuids": ["ref-1", "ref-2", None],
            },
        }

        assert _selected_refs_from_memory_inject(event) == {"ref-1", "ref-2"}

    def test_format_event_renders_memory_summary_content(self) -> None:
        event = {
            "turn": 1,
            "sequence": 1,
            "event_type": "memory_inject",
            "content": "loaded=57 refs:selected=3 index=29",
        }

        rendered = format_event(event)

        assert "[1.1] memory_inject" in rendered
        assert "loaded=57 refs:selected=3 index=29" in rendered
