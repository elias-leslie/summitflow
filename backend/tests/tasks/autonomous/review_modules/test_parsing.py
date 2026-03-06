"""Unit tests for parse_review_response in review_modules/parsing.py.

Covers all parsing strategies, hallucinated tool-call artifacts, keyword
fallbacks, and the NEEDS_FIX default — without touching external services.
"""

from __future__ import annotations

import json

import pytest

from app.tasks.autonomous.review_modules.parsing import (
    _strip_tool_call_artifacts,
    parse_review_response,
)

# ---------------------------------------------------------------------------
# _strip_tool_call_artifacts helpers
# ---------------------------------------------------------------------------


class TestStripToolCallArtifacts:
    """Unit tests for the internal artifact-stripping helper."""

    def test_removes_xml_tool_call_block(self) -> None:
        raw = "<tool_call>bash(ls -la)</tool_call> some trailing text"
        result = _strip_tool_call_artifacts(raw)
        assert "<tool_call>" not in result
        assert "some trailing text" in result

    def test_removes_xml_tool_result_block(self) -> None:
        raw = "<tool_result>output here</tool_result> verdict follows"
        result = _strip_tool_call_artifacts(raw)
        assert "<tool_result>" not in result
        assert "verdict follows" in result

    def test_removes_tool_use_json_object(self) -> None:
        raw = '{"type": "tool_use", "name": "bash", "input": {}} leftover'
        result = _strip_tool_call_artifacts(raw)
        assert '"type": "tool_use"' not in result
        assert "leftover" in result

    def test_passthrough_clean_content(self) -> None:
        raw = '{"verdict": "APPROVED", "concerns": [], "recommendation": "Ship it"}'
        result = _strip_tool_call_artifacts(raw)
        assert result == raw


# ---------------------------------------------------------------------------
# parse_review_response — happy paths
# ---------------------------------------------------------------------------


class TestParseReviewResponseHappyPaths:
    """Clean JSON inputs must be returned verbatim."""

    def test_approved_verdict_returned(self) -> None:
        payload = {
            "verdict": "APPROVED",
            "concerns": [],
            "recommendation": "Looks good",
        }
        result = parse_review_response(json.dumps(payload))
        assert result["verdict"] == "APPROVED"
        assert result["concerns"] == []
        assert result["recommendation"] == "Looks good"

    def test_needs_fix_verdict_with_concerns(self) -> None:
        payload = {
            "verdict": "NEEDS_FIX",
            "concerns": ["Missing test coverage", "Unused import"],
            "recommendation": "Fix the issues and re-submit",
        }
        result = parse_review_response(json.dumps(payload))
        assert result["verdict"] == "NEEDS_FIX"
        assert len(result["concerns"]) == 2
        assert "Missing test coverage" in result["concerns"]

    def test_plan_defect_verdict(self) -> None:
        payload = {
            "verdict": "PLAN_DEFECT",
            "concerns": ["Plan does not match implementation"],
            "recommendation": "Revisit plan",
        }
        result = parse_review_response(json.dumps(payload))
        assert result["verdict"] == "PLAN_DEFECT"

    def test_escalate_verdict(self) -> None:
        payload = {
            "verdict": "ESCALATE",
            "concerns": ["Security risk"],
            "recommendation": "Human review required",
        }
        result = parse_review_response(json.dumps(payload))
        assert result["verdict"] == "ESCALATE"

    def test_verdict_embedded_in_prose(self) -> None:
        """JSON block embedded in surrounding prose text."""
        content = (
            'Here is my review:\n\n'
            '{"verdict": "APPROVED", "concerns": [], "recommendation": "LGTM"}\n\n'
            "That's all."
        )
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"

    def test_verdict_in_fenced_code_block(self) -> None:
        """Reviewers sometimes wrap output in a fenced code block."""
        content = (
            "```json\n"
            '{"verdict": "NEEDS_FIX", "concerns": ["typo"], "recommendation": "Fix"}\n'
            "```"
        )
        result = parse_review_response(content)
        assert result["verdict"] == "NEEDS_FIX"

    def test_verdict_in_plain_fenced_block(self) -> None:
        """Fenced block without language identifier."""
        content = (
            "```\n"
            '{"verdict": "APPROVED", "concerns": []}\n'
            "```"
        )
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"


# ---------------------------------------------------------------------------
# parse_review_response — tool-use hallucination scenarios
# ---------------------------------------------------------------------------


class TestParseReviewResponseToolUseHallucinations:
    """The parser must recover valid verdicts buried under tool-call noise."""

    def test_tool_use_prefix_then_valid_verdict(self) -> None:
        """LLM emits a tool_use block first, then the real verdict JSON."""
        tool_use = '{"type": "tool_use", "name": "bash", "input": {}}'
        verdict = '{"verdict": "APPROVED", "concerns": [], "recommendation": "All good"}'
        content = f"{tool_use}\n\n{verdict}"
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"

    def test_xml_tool_call_before_verdict(self) -> None:
        """XML tool_call artifact precedes the actual verdict JSON."""
        content = (
            "<tool_call>run_tests()</tool_call>\n"
            '{"verdict": "NEEDS_FIX", "concerns": ["failing tests"]}'
        )
        result = parse_review_response(content)
        assert result["verdict"] == "NEEDS_FIX"
        assert "failing tests" in result["concerns"]

    def test_tool_call_xml_only_no_verdict_falls_back_to_keyword(self) -> None:
        """No JSON at all — only XML tool calls — but text has APPROVED keyword."""
        content = "<tool_call>bash(echo ok)</tool_call> The change is APPROVED."
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"

    def test_nested_tool_use_wrapping_verdict_in_input_key(self) -> None:
        """Verdict JSON is the value of 'input' inside a tool_use wrapper."""
        inner = {"verdict": "APPROVED", "concerns": [], "recommendation": "Ship it"}
        outer = {"type": "tool_use", "name": "review", "input": inner}
        content = json.dumps(outer)
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"

    def test_nested_tool_use_with_string_encoded_input(self) -> None:
        """'input' is a JSON string (double-encoded) rather than a dict."""
        inner = json.dumps(
            {"verdict": "NEEDS_FIX", "concerns": ["bad code"], "recommendation": "Redo"}
        )
        outer = {"type": "tool_use", "name": "review", "input": inner}
        content = json.dumps(outer)
        result = parse_review_response(content)
        assert result["verdict"] == "NEEDS_FIX"

    def test_tool_use_followed_by_verdict_in_fenced_block(self) -> None:
        """Hallucinated tool_use JSON then verdict in a fenced code block."""
        content = (
            '{"type": "tool_use", "name": "bash", "input": {}}\n\n'
            "```json\n"
            '{"verdict": "ESCALATE", "concerns": ["security"]}\n'
            "```"
        )
        result = parse_review_response(content)
        assert result["verdict"] == "ESCALATE"


# ---------------------------------------------------------------------------
# parse_review_response — keyword / text fallbacks
# ---------------------------------------------------------------------------


class TestParseReviewResponseKeywordFallback:
    """When no JSON is parseable, keyword scan determines the verdict."""

    def test_plain_text_with_approved_keyword(self) -> None:
        content = "After reviewing the diff, I believe the change is APPROVED."
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"
        assert "summary" in result

    def test_plain_text_with_plan_defect_keyword(self) -> None:
        content = "This has a PLAN_DEFECT — the implementation does not match the spec."
        result = parse_review_response(content)
        assert result["verdict"] == "PLAN_DEFECT"

    def test_plain_text_with_escalate_keyword(self) -> None:
        content = "This change requires ESCALATE to a human reviewer."
        result = parse_review_response(content)
        assert result["verdict"] == "ESCALATE"

    def test_keyword_match_is_case_insensitive(self) -> None:
        content = "The diff looks great. approved."
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"

    def test_approved_takes_precedence_in_keyword_scan(self) -> None:
        """APPROVED is checked first in the keyword scan order."""
        # Both APPROVED and PLAN_DEFECT are present; APPROVED wins per scan order
        content = "APPROVED but also flagging a PLAN_DEFECT for awareness."
        result = parse_review_response(content)
        assert result["verdict"] == "APPROVED"


# ---------------------------------------------------------------------------
# parse_review_response — default / unparseable
# ---------------------------------------------------------------------------


class TestParseReviewResponseDefault:
    """Truly unparseable content must default to NEEDS_FIX, not raise."""

    def test_empty_string_defaults_to_needs_fix(self) -> None:
        result = parse_review_response("")
        assert result["verdict"] == "NEEDS_FIX"

    def test_garbage_string_defaults_to_needs_fix(self) -> None:
        result = parse_review_response("x7q!@#$%^&*zzz")
        assert result["verdict"] == "NEEDS_FIX"

    def test_json_without_verdict_key_defaults_to_needs_fix(self) -> None:
        """Valid JSON but no 'verdict' field and no keyword → NEEDS_FIX."""
        content = '{"status": "ok", "message": "done"}'
        result = parse_review_response(content)
        assert result["verdict"] == "NEEDS_FIX"

    def test_tool_use_json_only_no_verdict_anywhere_defaults_to_needs_fix(self) -> None:
        """A pure tool_use block with no verdict and no keyword → NEEDS_FIX."""
        tool_use = json.dumps({"type": "tool_use", "name": "bash", "input": {}})
        result = parse_review_response(tool_use)
        assert result["verdict"] == "NEEDS_FIX"

    def test_malformed_json_defaults_to_needs_fix(self) -> None:
        result = parse_review_response("{verdict: }")  # malformed, no keyword
        assert result["verdict"] == "NEEDS_FIX"

    def test_result_always_contains_verdict_key(self) -> None:
        """Guarantee: parse_review_response always returns a dict with 'verdict'."""
        for content in ["", "gibberish", "{}", "null", "[]", "true"]:
            result = parse_review_response(content)
            assert "verdict" in result, f"Missing 'verdict' for input: {content!r}"

    @pytest.mark.parametrize("verdict", ["APPROVED", "NEEDS_FIX", "PLAN_DEFECT", "ESCALATE"])
    def test_all_valid_verdicts_are_preserved(self, verdict: str) -> None:
        payload = {"verdict": verdict, "concerns": []}
        result = parse_review_response(json.dumps(payload))
        assert result["verdict"] == verdict
