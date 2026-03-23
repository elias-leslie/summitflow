"""Tests for explorer-backed context gathering."""

from __future__ import annotations

from unittest.mock import patch

from app.services.context_gatherer.explorer_collector import gather_explorer_context
from app.services.context_gatherer.precision_code_search import (
    collect_precision_code_search_context,
)


def test_gather_explorer_context_includes_symbol_matches() -> None:
    """Relevant symbol matches should be included ahead of broader file listings."""
    expected = "Precision Code Search: symbol-first\n\n## Relevant Symbols\n\n- `get_file_tree` ..."
    with patch(
        "app.services.context_gatherer.explorer_collector.collect_precision_code_search_context"
    ) as mock_collect:
        mock_collect.return_value.prompt_context = expected
        context = gather_explorer_context("project-1", "get_file_tree")

    mock_collect.assert_called_once()
    assert "Precision Code Search: symbol-first" in context
    assert "## Relevant Symbols" in context
    assert "`get_file_tree`" in context


def test_collect_precision_code_search_context_tracks_token_savings() -> None:
    with (
        patch("app.services.context_gatherer._precision_ranking.search_symbols") as mock_search,
        patch(
            "app.services.context_gatherer._precision_sections.list_related_entries_for_file"
        ) as mock_related,
        patch("app.services.context_gatherer._precision_sections.get_symbol") as mock_get_symbol,
        patch(
            "app.services.context_gatherer.precision_code_search.estimate_naive_file_tokens",
            return_value=2000,
        ),
        patch(
            "app.services.context_gatherer._precision_sections.read_symbol_source"
        ) as mock_read_symbol_source,
    ):
        mock_search.return_value = [
            {
                "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                "qualified_name": "get_file_tree",
                "name": "get_file_tree",
                "kind": "function",
                "file_path": "backend/app/api/files.py",
                "start_line": 7,
                "end_line": 9,
                "signature": "def get_file_tree(path: str) -> dict[str, str]",
                "summary": "List directory entries for file tree navigation.",
            }
        ]
        mock_related.return_value = []
        mock_get_symbol.return_value = {
            "symbol_id": "backend/app/api/files.py::get_file_tree#function",
            "qualified_name": "get_file_tree",
            "file_path": "backend/app/api/files.py",
            "start_line": 7,
            "end_line": 9,
        }
        mock_read_symbol_source.return_value = "def get_file_tree(path: str) -> dict[str, str]: ..."

        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    assert result.metadata["used_symbol_first"]
    assert result.metadata["symbol_count"] == 1
    assert result.metadata["naive_file_tokens"] == 2000
    assert result.metadata["estimated_tokens_saved"] > 0
    assert "Exact Source Slices" in result.prompt_context


def test_collect_precision_code_search_context_skips_workflow_meta_queries() -> None:
    result = collect_precision_code_search_context(
        "project-1",
        [
            "Run one no-code autonomous validation task through the updated workflow and confirm it no longer fails on missing work product or irrelevant Precision Code Search injection."
        ],
    )

    assert result.prompt_context == ""
    assert result.metadata["skipped_reason"] == "workflow_meta_low_signal"


def test_collect_precision_code_search_context_formats_text_fallback_matches() -> None:
    with (
        patch("app.services.context_gatherer._precision_ranking.search_symbols", return_value=[]),
        patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            return_value={
                "items": [
                    {
                        "path": "backend/app/api/tasks.py",
                        "line": 12,
                        "content": 'router = APIRouter(tags=["tasks api"])',
                        "language": "python",
                    }
                ],
                "count": 1,
                "files_searched": 2,
                "truncated": False,
            },
        ),
    ):
        result = collect_precision_code_search_context("project-1", ["tasks api"])

    assert "backend/app/api/tasks.py" in result.prompt_context
    assert "tasks api" in result.prompt_context
    assert result.metadata["fallback_mode"] == "text"
    assert result.metadata["text_match_count"] == 1


def test_collect_precision_code_search_context_skips_fallback_fetch_on_symbol_hits() -> None:
    with (
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            return_value=[
                {
                    "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                    "qualified_name": "get_file_tree",
                    "name": "get_file_tree",
                    "kind": "function",
                    "file_path": "backend/app/api/files.py",
                    "start_line": 7,
                    "end_line": 9,
                    "signature": "def get_file_tree(path: str) -> dict[str, str]",
                    "summary": "List directory entries for file tree navigation.",
                }
            ],
        ),
        patch(
            "app.services.context_gatherer._precision_sections.list_related_entries_for_file",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer._precision_sections.get_symbol",
            return_value={
                "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                "qualified_name": "get_file_tree",
                "file_path": "backend/app/api/files.py",
                "start_line": 7,
                "end_line": 9,
            },
        ),
        patch(
            "app.services.context_gatherer._precision_sections.read_symbol_source",
            return_value="def get_file_tree(path: str) -> dict[str, str]: ...",
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.estimate_naive_file_tokens",
            return_value=2000,
        ),
        patch("app.services.context_gatherer.precision_code_search.search_text") as mock_search_text,
    ):
        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    mock_search_text.assert_not_called()
    assert result.metadata["used_symbol_first"]
    assert not result.metadata["used_fallback"]


def test_collect_precision_code_search_context_uses_text_search_primitive_for_fallback() -> None:
    with (
        patch("app.services.context_gatherer._precision_ranking.search_symbols", return_value=[]),
        patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            return_value={
                "items": [
                    {
                        "path": "backend/app/api/files.py",
                        "line": 8,
                        "content": '    marker = "special fallback token"',
                        "language": "python",
                    }
                ],
                "count": 1,
                "files_searched": 4,
                "truncated": False,
            },
        ) as mock_search_text,
    ):
        result = collect_precision_code_search_context("project-1", ["special fallback token"])

    mock_search_text.assert_called_once_with("project-1", "special fallback token", limit=12)
    assert result.metadata["used_symbol_first"] is False
    assert result.metadata["used_fallback"] is True
    assert result.metadata["fallback_mode"] == "text"
    assert result.metadata["text_match_count"] == 1
    assert "## Relevant Text Matches" in result.prompt_context
    assert "backend/app/api/files.py:8" in result.prompt_context


def test_collect_precision_code_search_context_ranks_multi_term_matches_by_coverage() -> None:
    """Multi-term queries should not let early broad hits crowd out better later matches."""

    def _search_side_effect(project_id: str, query: str, limit: int = 50) -> list[dict[str, object]]:
        assert project_id == "project-1"
        assert limit >= 5
        quality_symbols = [
            {
                "symbol_id": "backend/app/tasks/autonomous/exec_modules/quality_gates.py::auto_fix_quality#function",
                "qualified_name": "auto_fix_quality",
                "name": "auto_fix_quality",
                "kind": "function",
                "file_path": "backend/app/tasks/autonomous/exec_modules/quality_gates.py",
                "start_line": 112,
                "end_line": 141,
                "signature": "def auto_fix_quality(project_path: str, project_id: str) -> bool",
                "summary": "Run dt --fix to attempt auto-fixing quality issues.",
            },
            {
                "symbol_id": "frontend/components/health/NeedsAttentionCard.test.tsx::createMockQualityCheck#function",
                "qualified_name": "createMockQualityCheck",
                "name": "createMockQualityCheck",
                "kind": "function",
                "file_path": "frontend/components/health/NeedsAttentionCard.test.tsx",
                "start_line": 8,
                "end_line": 20,
                "signature": "function createMockQualityCheck(overrides: Partial<CheckResult> = {}): CheckResult",
                "summary": "Build a mock quality check result for frontend tests.",
            },
            {
                "symbol_id": "backend/app/tasks/autonomous/exec_modules/ah_events.py::emit_quality_gate_result#function",
                "qualified_name": "emit_quality_gate_result",
                "name": "emit_quality_gate_result",
                "kind": "function",
                "file_path": "backend/app/tasks/autonomous/exec_modules/ah_events.py",
                "start_line": 108,
                "end_line": 125,
                "signature": "def emit_quality_gate_result(task_id: str, passed: bool, detail: str = '') -> None",
                "summary": "Emit a quality gate pass or fail event.",
            },
            {
                "symbol_id": "frontend/lib/api/projects.ts::fetchQualityGateHealth#function",
                "qualified_name": "fetchQualityGateHealth",
                "name": "fetchQualityGateHealth",
                "kind": "function",
                "file_path": "frontend/lib/api/projects.ts",
                "start_line": 70,
                "end_line": 74,
                "signature": "export async function fetchQualityGateHealth(id: string): Promise<QualityGateHealth>",
                "summary": "Fetch quality gate health for a project.",
            },
            {
                "symbol_id": "backend/app/storage/agent_configs_quality.py::get_quality_gate_fix_enabled#function",
                "qualified_name": "get_quality_gate_fix_enabled",
                "name": "get_quality_gate_fix_enabled",
                "kind": "function",
                "file_path": "backend/app/storage/agent_configs_quality.py",
                "start_line": 40,
                "end_line": 50,
                "signature": "def get_quality_gate_fix_enabled(project_id: str) -> bool",
                "summary": "Check if auto-fix is enabled for quality gates.",
            },
        ]
        health_symbols = [
            {
                "symbol_id": "backend/app/api/quality_gate.py::get_health_summary#function",
                "qualified_name": "get_health_summary",
                "name": "get_health_summary",
                "kind": "function",
                "file_path": "backend/app/api/quality_gate.py",
                "start_line": 24,
                "end_line": 35,
                "signature": "async def get_health_summary(project_id: str) -> HealthSummaryResponse",
                "summary": "Get quality gate health summary for a project.",
            }
        ]
        if query in ("quality health api", "api"):
            return []
        if query == "quality":
            return quality_symbols
        if query == "health":
            return health_symbols
        return []

    with (
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            side_effect=_search_side_effect,
        ),
        patch(
            "app.services.context_gatherer._precision_sections.list_related_entries_for_file"
        ) as mock_related,
        patch("app.services.context_gatherer._precision_sections.get_symbol") as mock_get_symbol,
        patch(
            "app.services.context_gatherer._precision_sections.read_symbol_source",
            return_value="async def get_health_summary(project_id: str) -> HealthSummaryResponse: ...",
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.estimate_naive_file_tokens",
            return_value=3000,
        ),
    ):
        mock_related.side_effect = lambda _project_id, file_path: (
            [
                {
                    "entry_type": "endpoint",
                    "path": "/projects/{project_id}/quality/health",
                    "metadata": {"depends_on_tables": ["quality_check_results"]},
                }
            ]
            if file_path == "backend/app/api/quality_gate.py"
            else []
        )
        mock_get_symbol.side_effect = lambda _project_id, symbol_id: (
            {
                "symbol_id": symbol_id,
                "qualified_name": "get_health_summary",
                "file_path": "backend/app/api/quality_gate.py",
                "start_line": 24,
                "end_line": 35,
                "byte_offset": 0,
                "byte_length": 0,
            }
            if symbol_id == "backend/app/api/quality_gate.py::get_health_summary#function"
            else None
        )

        result = collect_precision_code_search_context("project-1", ["quality health api"])

    assert result.metadata["used_symbol_first"]
    assert result.metadata["symbol_count"] == 5
    assert "`get_health_summary`" in result.prompt_context
    assert "/projects/{project_id}/quality/health" in result.prompt_context


def test_collect_precision_code_search_context_refreshes_stale_file_index() -> None:
    with (
        patch(
            "app.services.context_gatherer.precision_code_search.explorer_service.get_stats",
            return_value={"total": 12, "last_scanned": "2026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_symbol_stats",
            return_value={"count": 4, "last_updated": "2026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.explorer_service.scan"
        ) as mock_scan,
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            return_value={"items": [], "count": 0, "files_searched": 0, "truncated": False},
        ),
    ):
        mock_scan.return_value.success = True
        mock_scan.return_value.entries_found = 12
        mock_scan.return_value.entries_saved = 12
        mock_scan.return_value.duration_ms = 100

        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    mock_scan.assert_called_once_with("project-1", "file")
    assert result.metadata["refreshed_index"]
    assert result.metadata["stale_hit"]
    assert result.metadata["refresh_reasons"] == ["stale_file_index", "stale_symbol_index"]
    assert result.metadata["file_index_age_minutes"] is not None
    assert result.metadata["symbol_index_age_minutes"] is not None


def test_collect_precision_code_search_context_skips_refresh_for_workflow_meta_queries() -> None:
    with patch(
        "app.services.context_gatherer.precision_code_search.explorer_service.scan"
    ) as mock_scan:
        result = collect_precision_code_search_context(
            "project-1",
            ["Confirm workflow cleanup status and closeout coordination."],
        )

    mock_scan.assert_not_called()
    assert result.metadata["skipped_reason"] == "workflow_meta_low_signal"


def test_collect_precision_code_search_context_tracks_fresh_index_telemetry() -> None:
    with (
        patch(
            "app.services.context_gatherer.precision_code_search.explorer_service.get_stats",
            return_value={"total": 12, "last_scanned": "3026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_symbol_stats",
            return_value={"count": 4, "last_updated": "3026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            return_value={"items": [], "count": 0, "files_searched": 0, "truncated": False},
        ),
    ):
        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    assert not result.metadata["stale_hit"]
    assert result.metadata["refresh_reasons"] == []
    assert result.metadata["file_total"] == 12
    assert result.metadata["file_last_scanned"] == "3026-03-10T17:00:00+00:00"
    assert result.metadata["symbol_last_updated"] == "3026-03-10T17:00:00+00:00"


def test_collect_precision_code_search_context_respects_symbol_limit() -> None:
    """symbol_limit parameter should control how many symbols are returned."""

    def _search_side_effect(project_id: str, query: str, limit: int = 50) -> list[dict[str, object]]:
        return [
            {
                "symbol_id": f"sym_{i}",
                "qualified_name": f"func_{i}",
                "name": f"func_{i}",
                "kind": "function",
                "file_path": f"backend/mod{i}.py",
                "start_line": i * 10,
                "end_line": i * 10 + 5,
                "signature": f"def func_{i}()",
                "summary": f"Function {i}",
            }
            for i in range(10)
        ]

    with (
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            side_effect=_search_side_effect,
        ),
        patch(
            "app.services.context_gatherer._precision_sections.list_related_entries_for_file",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer._precision_sections.get_symbol",
            return_value=None,
        ),
        patch(
            "app.services.context_gatherer._precision_sections.read_symbol_source",
            return_value="def func(): ...",
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.estimate_naive_file_tokens",
            return_value=5000,
        ),
    ):
        result_default = collect_precision_code_search_context("project-1", ["func"])
        result_limited = collect_precision_code_search_context("project-1", ["func"], symbol_limit=3)

    assert result_default.metadata["symbol_count"] == 5  # default _SEARCH_LIMIT
    assert result_limited.metadata["symbol_count"] == 3


def test_collect_precision_code_search_context_routes_natural_language_to_text() -> None:
    """NL queries try symbol search with case variants first, fall back to text if no symbols."""
    with (
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            return_value=[],  # No symbol matches for NL variants
        ) as mock_symbols,
        patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            return_value={
                "items": [
                    {
                        "path": "backend/app/storage/explorer_symbols.py",
                        "line": 237,
                        "content": "CASE WHEN LOWER(name) = %s THEN 100",
                        "language": "python",
                    }
                ],
                "count": 1,
                "files_searched": 5,
                "truncated": False,
            },
        ),
    ):
        result = collect_precision_code_search_context("project-1", ["scoring logic"])

    # NL queries now try symbol search with case variants (e.g. "ScoringLogic")
    mock_symbols.assert_called()
    assert result.metadata["used_fallback"] is True
    assert result.metadata["fallback_mode"] == "text"


def test_collect_precision_code_search_context_nl_query_finds_symbols_via_case_variants() -> None:
    """NL query 'project selector' should find ProjectSelector symbol via case expansion."""
    with (
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
        ) as mock_symbols,
        patch(
            "app.services.context_gatherer._precision_sections.list_related_entries_for_file",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer._precision_sections.get_symbol",
            return_value={
                "symbol_id": "frontend/components/layout/ProjectSelector.tsx::ProjectSelector#function",
                "qualified_name": "ProjectSelector",
                "file_path": "frontend/components/layout/ProjectSelector.tsx",
                "start_line": 21,
                "end_line": 180,
            },
        ),
        patch(
            "app.services.context_gatherer._precision_sections.read_symbol_source",
            return_value="export function ProjectSelector({ onProjectChange }: Props) {",
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.estimate_naive_file_tokens",
            return_value=2000,
        ),
    ):
        mock_symbols.return_value = [
            {
                "symbol_id": "frontend/components/layout/ProjectSelector.tsx::ProjectSelector#function",
                "qualified_name": "ProjectSelector",
                "name": "ProjectSelector",
                "kind": "function",
                "file_path": "frontend/components/layout/ProjectSelector.tsx",
                "start_line": 21,
                "end_line": 180,
                "signature": "export function ProjectSelector({ onProjectChange })",
                "summary": "Project selection dropdown component.",
            }
        ]

        result = collect_precision_code_search_context("project-1", ["project selector"])

    # NL query should find symbols via CamelCase expansion ("ProjectSelector")
    assert result.metadata["used_symbol_first"] is True
    assert result.metadata["symbol_count"] == 1
    assert "ProjectSelector" in result.prompt_context


def test_collect_precision_code_search_context_text_fallback_tries_individual_terms() -> None:
    """When full-phrase text search finds nothing, individual terms should be tried."""
    call_count = 0

    def _search_text_side_effect(project_id: str, query: str, *, limit: int = 20) -> dict:
        nonlocal call_count
        call_count += 1
        if " " in query:
            # Full phrase "open settings" finds nothing
            return {"items": [], "count": 0, "files_searched": 10, "truncated": False}
        # Individual term "settings" finds results
        if query == "settings":
            return {
                "items": [
                    {
                        "path": "backend/app/config.py",
                        "line": 15,
                        "content": "class Settings(BaseSettings):",
                        "language": "python",
                    }
                ],
                "count": 1,
                "files_searched": 10,
                "truncated": False,
            }
        return {"items": [], "count": 0, "files_searched": 10, "truncated": False}

    with (
        patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.search_text",
            side_effect=_search_text_side_effect,
        ),
    ):
        result = collect_precision_code_search_context("project-1", ["open settings"])

    assert call_count >= 2  # At least phrase + one individual term
    assert result.metadata["used_fallback"] is True
    assert result.metadata["text_match_count"] == 1
    assert "config.py" in result.prompt_context
