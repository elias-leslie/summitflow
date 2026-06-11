"""Tests for precision code search fallback and metadata helpers."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.services.context_gatherer.precision_code_search import (
    _definition_matched_terms,
    _per_term_text_union,
    _text_fallback,
)


def _text_result(items: list[dict[str, Any]], *, truncated: bool = False, files: int = 10) -> dict[str, Any]:
    return {"count": len(items), "files_searched": files, "items": items, "truncated": truncated}


class TestPerTermTextUnion:
    def test_phrase_miss_unions_rare_terms(self) -> None:
        results = {
            "_lever_impacts spend_less": _text_result([]),
            "_lever_impacts": _text_result([{"path": "a.py", "line": 1, "content": "def _lever_impacts("}]),
            "spend_less": _text_result([{"path": "a.py", "line": 9, "content": '"spend_less",'}]),
        }
        with patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            side_effect=lambda pid, q, **kw: results[q],
        ):
            text_results, section = _text_fallback("p1", ["_lever_impacts spend_less"], "")

        assert text_results["per_term_union"] is True
        assert [(i["path"], i["line"]) for i in text_results["items"]] == [("a.py", 1), ("a.py", 9)]
        assert section

    def test_common_word_terms_are_dropped_from_union(self) -> None:
        junk = [{"path": f"f{i}.py", "line": i, "content": "session everywhere"} for i in range(12)]
        results = {
            "session rare_identifier": _text_result([]),
            "session": _text_result(junk, truncated=True),
            "rare_identifier": _text_result([{"path": "b.py", "line": 5, "content": "rare_identifier = 1"}]),
        }
        with patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            side_effect=lambda pid, q, **kw: results[q],
        ):
            union = _per_term_text_union("p1", "session rare_identifier")

        assert union is not None
        assert [i["path"] for i in union["items"]] == ["b.py"]

    def test_single_term_phrase_does_not_retry(self) -> None:
        with patch(
            "app.services.context_gatherer.precision_code_search.search_text",
        ) as mock_search:
            assert _per_term_text_union("p1", "lone_term") is None
        mock_search.assert_not_called()

    def test_all_terms_junk_returns_none(self) -> None:
        junk = [{"path": f"f{i}.py", "line": i, "content": "x"} for i in range(12)]
        with patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            return_value=_text_result(junk, truncated=True),
        ):
            assert _per_term_text_union("p1", "session request") is None

    def test_duplicate_lines_across_terms_dedupe(self) -> None:
        shared = {"path": "a.py", "line": 3, "content": "alpha_thing beta_thing"}
        results = {
            "alpha_thing beta_thing zzz_qqq": _text_result([]),
            "alpha_thing": _text_result([shared]),
            "beta_thing": _text_result([dict(shared)]),
            "zzz_qqq": _text_result([]),
        }
        with patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            side_effect=lambda pid, q, **kw: results[q],
        ):
            union = _per_term_text_union("p1", "alpha_thing beta_thing zzz_qqq")

        assert union is not None
        assert union["count"] == 1


class TestDefinitionMatchedTerms:
    def test_detects_definition_line(self) -> None:
        items = [{"path": "a.py", "line": 61, "content": "def tool_not_installed(name: str, root: Path) -> bool:"}]
        assert _definition_matched_terms(["tool_not_installed"], items) == ["tool_not_installed"]

    def test_ignores_call_sites(self) -> None:
        items = [
            {"path": "a.py", "line": 109, "content": "if isinstance(exc, FileNotFoundError) and tool_not_installed(name, root):"},
            {"path": "a.py", "line": 39, "content": "tool_not_installed,"},
        ]
        assert _definition_matched_terms(["tool_not_installed"], items) == []

    def test_detects_class_and_const_definitions(self) -> None:
        items = [
            {"path": "a.ts", "line": 2, "content": "const RetryBudget = makeBudget()"},
            {"path": "b.py", "line": 8, "content": "class PaymentRouter:"},
        ]
        assert _definition_matched_terms(["PaymentRouter RetryBudget"], items) == ["PaymentRouter", "RetryBudget"]

    def test_empty_items_returns_empty(self) -> None:
        assert _definition_matched_terms(["anything"], []) == []
        assert _definition_matched_terms(["anything"], None) == []
