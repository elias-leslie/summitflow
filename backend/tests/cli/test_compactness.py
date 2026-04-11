"""Tests for compactness heuristics used by prompt and memory authoring flows."""

from __future__ import annotations

from cli.commands.compactness import analyze_compactness


class TestCompactnessHeuristics:
    def test_prompt_flags_large_filler_heavy_content(self) -> None:
        report = analyze_compactness(
            (
                "Please keep this prompt really clear.\n"
                + ("Example: keep signal.\n" * 90)
            ),
            kind="prompt",
        )

        assert report.tokens > 350
        assert any("large prompt" in warning for warning in report.warnings)
        assert any("long prompt" in warning for warning in report.warnings)
        assert any("filler terms found" in warning for warning in report.warnings)
        assert any("repeated example markers" in warning for warning in report.warnings)

    def test_memory_flags_long_multi_line_content(self) -> None:
        report = analyze_compactness(
            (
                "**Prompt Hygiene**: Keep prompts compact and focused.\n"
                "Use one canonical prompt.\n"
                "Drop overlap.\n"
                "Drop filler.\n"
                "Split extra rules."
            ),
            kind="memory",
        )

        assert report.chars > 100
        assert any("multi-line memory" in warning for warning in report.warnings)

    def test_lean_content_stays_warning_free(self) -> None:
        report = analyze_compactness(
            "**Quality Checks**: Use dt for repo checks.",
            kind="memory",
        )

        assert report.warnings == ()
