"""Source-backed compatibility coverage for hosted precision context gathering."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from code_intelligence.analyzers import extract_symbols
from code_intelligence.precision import ranking
from code_intelligence.precision.token_utils import estimate_tokens

from app.services.context_gatherer import precision_code_search as adapter
from app.services.context_gatherer.explorer_collector import gather_explorer_context


@pytest.fixture
def source_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[dict[str, Any]]]:
    root = tmp_path / "project"
    root.mkdir()
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(adapter.explorer_service, "get_project_root", lambda _: str(root))
    monkeypatch.setattr(adapter, "_get_precision_index_status", lambda _: {
        "should_refresh": False, "refresh_reasons": [], "file_total": 1,
    })
    monkeypatch.setattr(ranking, "search_symbols", lambda _project, q, **_: [
        row for row in rows if q.lower() in " ".join(str(row.get(k, "")) for k in (
            "name", "qualified_name", "file_path", "signature", "summary",
        )).lower()
    ])
    return root, rows


def index_source(project: tuple[Path, list[dict[str, Any]]], path: str, content: str) -> Path:
    root, rows = project
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    rows.extend({**row, "file_path": path} for row in extract_symbols(target, path))
    return target


def test_gather_explorer_context_includes_symbol_matches() -> None:
    expected = "Precision Code Search: symbol-first\n\n- `get_file_tree`"
    with patch("app.services.context_gatherer.explorer_collector.collect_precision_code_search_context") as collect:
        collect.return_value.prompt_context = expected
        assert expected in gather_explorer_context("project-1", "get_file_tree")
    collect.assert_called_once()


def test_accounting_uses_actual_final_prompt_and_unique_source_files(source_project) -> None:
    target = index_source(source_project, "files.py", "# context\n" * 100 + "def get_file_tree(path):\n    return {'path': path}\n")
    result = adapter.collect_precision_code_search_context("project-1", ["get_file_tree"])
    assert "return {'path': path}" in result.prompt_context
    assert result.metadata["source_verified"] is True
    assert result.metadata["measurement_available"] is True
    assert result.metadata["final_tokens"] == estimate_tokens(result.prompt_context)
    assert result.metadata["naive_file_tokens"] == estimate_tokens(target.read_text())
    assert result.metadata["estimated_tokens_saved"] == max(
        estimate_tokens(target.read_text()) - estimate_tokens(result.prompt_context), 0,
    )


@pytest.mark.parametrize("query", ["ProjectSelector", "project selector", "where is the project selector"])
def test_natural_language_and_exact_queries_find_current_definition(source_project, query) -> None:
    index_source(source_project, "selector.tsx", "export function ProjectSelector() {\n  return <div>Select</div>;\n}\n")
    result = adapter.collect_precision_code_search_context("project-1", [query])
    assert "ProjectSelector" in result.prompt_context
    assert "<div>Select</div>" in result.prompt_context
    assert result.metadata["used_symbol_first"] is True


def test_existing_hit_is_refreshed_after_source_shift_and_edit(source_project) -> None:
    target = index_source(source_project, "files.py", "def get_file_tree(path):\n    return path\n")
    target.write_text("# café\n\ndef get_file_tree(path):\n    return path.strip()\n")
    result = adapter.collect_precision_code_search_context("project-1", ["get_file_tree"], include_candidates=True)
    assert "return path.strip()" in result.prompt_context
    assert result.candidates and result.candidates[0]["start_line"] == 3
    assert result.metadata["source_verified"] is True


def test_partial_index_match_does_not_hide_new_exact_definition(source_project) -> None:
    root, _rows = source_project
    index_source(source_project, "consumer.py", "def consume(value: ProgramRevisionInput):\n    return value\n")
    (root / "models.py").write_text("class ProgramRevisionInput:\n    revision: int\n    source: str\n")
    result = adapter.collect_precision_code_search_context("project-1", ["ProgramRevisionInput"])
    assert "class ProgramRevisionInput:" in result.prompt_context
    assert "revision: int" in result.prompt_context
    assert result.prompt_context.index("ProgramRevisionInput") < result.prompt_context.index("consume")


def test_deleted_symbol_does_not_survive_index_hit(source_project) -> None:
    target = index_source(source_project, "files.py", "def removed_function():\n    return 'removed'\n")
    target.unlink()
    result = adapter.collect_precision_code_search_context("project-1", ["removed_function"])
    assert "return 'removed'" not in result.prompt_context
    assert result.metadata["symbol_count"] == 0


def test_file_rename_recovers_current_path(source_project) -> None:
    root, _rows = source_project
    target = index_source(source_project, "old.py", "def renamed_function():\n    return 42\n")
    target.rename(root / "new.py")
    result = adapter.collect_precision_code_search_context("project-1", ["renamed_function"])
    assert "new.py:1" in result.prompt_context
    assert "old.py:" not in result.prompt_context


def test_import_query_preserves_text_mode_and_line_evidence(source_project) -> None:
    root, _rows = source_project
    (root / "imports.py").write_text("from pathlib import Path\n")
    result = adapter.collect_precision_code_search_context("project-1", ["from pathlib import Path"])
    assert result.metadata["used_fallback"] is True
    assert "imports.py:1" in result.prompt_context


def test_phrase_fallback_and_rare_term_union_keep_both_terms(source_project) -> None:
    root, _rows = source_project
    (root / "data.txt").write_text("alpha_thing first\nbeta_thing second\n")
    result = adapter.collect_precision_code_search_context("project-1", ["alpha_thing beta_thing"])
    assert "alpha_thing first" in result.prompt_context
    assert "beta_thing second" in result.prompt_context
    assert result.metadata["text_match_count"] == 2


def test_absent_query_stays_empty_without_rescan(source_project) -> None:
    with patch.object(adapter.explorer_service, "scan") as scan:
        result = adapter.collect_precision_code_search_context("project-1", ["truly_absent_symbol"])
    scan.assert_not_called()
    assert result.prompt_context == ""
    assert result.metadata["symbol_count"] == 0
    assert result.metadata["text_match_count"] == 0
    assert result.metadata["measurement_available"] is False


def test_budget_is_honest_and_truncation_explicit(source_project) -> None:
    index_source(source_project, "large.py", "def large_function():\n" + "    value = 'context'\n" * 100)
    result = adapter.collect_precision_code_search_context("project-1", ["large_function"], budget_tokens=100)
    assert estimate_tokens(result.prompt_context) <= 100
    assert result.metadata["prompt_truncated"] is True
    assert result.metadata["final_tokens"] == estimate_tokens(result.prompt_context)


def test_symbol_limit_and_path_restriction(source_project) -> None:
    index_source(source_project, "one.py", "def helper_one():\n    return 1\n\ndef helper_two():\n    return 2\n")
    index_source(source_project, "other.py", "def helper_other():\n    return 3\n")
    result = adapter.collect_precision_code_search_context("project-1", ["helper"], symbol_limit=1, path_prefix="one.py")
    assert result.metadata["symbol_count"] == 1
    assert "other.py" not in result.prompt_context


def test_transport_candidates_are_opt_in(source_project) -> None:
    index_source(source_project, "files.py", "def get_file_tree(path):\n    return path\n")
    ordinary = adapter.collect_precision_code_search_context("project-1", ["get_file_tree"])
    transport = adapter.collect_precision_code_search_context("project-1", ["get_file_tree"], include_candidates=True)
    assert ordinary.candidates is None
    assert transport.candidates
    assert transport.prompt_context == ordinary.prompt_context
    assert all("source" not in candidate for candidate in transport.candidates)


def test_index_outage_still_returns_verified_local_source(source_project, monkeypatch) -> None:
    root, _rows = source_project
    (root / "local.py").write_text("def local_function():\n    return 'available'\n")
    def unavailable(*_args, **_kwargs):
        raise ConnectionError("unavailable")
    monkeypatch.setattr(ranking, "search_symbols", unavailable)
    result = adapter.collect_precision_code_search_context("project-1", ["local_function"])
    assert "return 'available'" in result.prompt_context
    assert result.metadata["source_verified"] is True
