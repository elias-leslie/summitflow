"""Tests for session events memory summaries."""

from __future__ import annotations

from cli.commands.session_events_formatter import (
    _format_memory_event_content,
    _render_memory_effectiveness_summary,
    _selected_refs_from_memory_inject,
    build_memory_effectiveness_summary,
    format_event,
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

    def test_build_memory_effectiveness_summary_aggregates_per_session(self) -> None:
        events = [
            {
                "session_id": "session-aaa11111",
                "event_type": "memory_inject",
                "tool_input": {
                    "reference_selected_count": 3,
                    "reference_index_count": 29,
                    "reference_selected_uuids": ["ref-1", "ref-2", "ref-3"],
                },
            },
            {
                "session_id": "session-aaa11111",
                "event_type": "memory_cite",
                "tool_input": {"uuids": ["ref-1", "mandate-1", "ref-2"]},
            },
            {
                "session_id": "session-bbb22222",
                "event_type": "memory_inject",
                "tool_input": {
                    "reference_selected_count": 1,
                    "reference_index_count": 4,
                    "reference_selected_uuids": ["ref-9"],
                },
            },
            {
                "session_id": "session-bbb22222",
                "event_type": "memory_cite",
                "tool_input": {"uuids": ["guardrail-1"]},
            },
        ]

        summary = build_memory_effectiveness_summary(events)

        assert summary["session-aaa11111"]["selected"] == 3
        assert summary["session-aaa11111"]["indexed"] == 29
        assert summary["session-aaa11111"]["selected_cited"] == 2
        assert summary["session-bbb22222"]["selected"] == 1
        assert summary["session-bbb22222"]["selected_cited"] == 0

    def test_render_memory_effectiveness_summary_for_task_shows_total_and_per_session(self) -> None:
        events = [
            {
                "session_id": "session-aaa11111",
                "event_type": "memory_inject",
                "tool_input": {
                    "reference_selected_count": 3,
                    "reference_index_count": 29,
                    "reference_selected_uuids": ["ref-1", "ref-2", "ref-3"],
                },
            },
            {
                "session_id": "session-aaa11111",
                "event_type": "memory_cite",
                "tool_input": {"uuids": ["ref-1", "ref-2"]},
            },
            {
                "session_id": "session-bbb22222",
                "event_type": "memory_inject",
                "tool_input": {
                    "reference_selected_count": 1,
                    "reference_index_count": 4,
                    "reference_selected_uuids": ["ref-9"],
                },
            },
        ]

        lines = _render_memory_effectiveness_summary(
            events,
            ["session-aaa11111", "session-bbb22222"],
        )

        assert lines[0] == " Memory:"
        assert "total selected=4 | index=33 | selected cited=2/4 (50%)" in lines[1]
        assert "aaa11111: refs=3 | index=29 | selected cited=2/3 (67%)" in lines[2]
        assert "bbb22222: refs=1 | index=4 | selected cited=0/1 (0%)" in lines[3]
