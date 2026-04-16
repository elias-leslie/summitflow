"""Tests for `st search` CLI behavior."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands import search as search_command
from cli.commands.search import app

runner = CliRunner()


def _invoke(args: list[str]) -> Any:
    project_root = Path("/srv/workspaces/projects/summitflow")
    if isinstance(search_command.resolve_checkout_root, MagicMock) or isinstance(search_command.canonical_repo_root, MagicMock):
        return runner.invoke(app, args)
    with (
        patch("cli.commands.search.resolve_checkout_root", return_value=project_root, create=True),
        patch("cli.commands.search.canonical_repo_root", return_value=project_root, create=True),
    ):
        return runner.invoke(app, args)


def _mock_client(result: Mapping[str, Any]) -> MagicMock:
    client = MagicMock()
    client._url.side_effect = lambda path: f"http://testserver{path}"
    client.get.return_value = result
    return client


def _immediate_status_timer(message: str) -> MagicMock:
    search_command._emit_status(message)
    timer = MagicMock()
    timer.cancel.return_value = None
    return timer


def test_search_compact_output_renders_prompt_context() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols\n\n- `proxy_complete`",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 1200,
            "final_tokens": 300,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["proxy_complete"])

    assert result.exit_code == 0
    assert "SEARCH:proxy_complete|mode=symbol-first|symbols=1|tokens=300|saved=1200" in result.output
    assert "## Relevant Symbols" in result.output
    mock_client.return_value.get.assert_called_once()


def test_search_json_output_emits_full_payload() -> None:
    payload = {
        "query": "proxy_complete",
        "prompt_context": "Precision Code Search: symbol-first",
        "metadata": {"symbol_count": 1, "used_symbol_first": True},
    }

    with patch("cli.commands.search.STClient", return_value=_mock_client(payload)):
        result = _invoke(["proxy_complete", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload


def test_search_project_override_uses_requested_project() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first",
        "metadata": {"symbol_count": 1, "used_symbol_first": True},
    }

    with patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client:
        result = _invoke(["proxy_complete", "--project", "agent-hub", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    mock_client.assert_called_once_with(project_id="agent-hub")


def test_search_compact_output_reports_empty_results() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["missing_symbol"])

    assert result.exit_code == 0
    assert "SEARCH:missing_symbol|mode=empty|symbols=0|tokens=0" in result.output


def test_search_empty_result_shows_hint() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["missing_symbol"])

    assert result.exit_code == 0
    assert "hint:" in result.output


def test_search_empty_result_no_hint_flag_suppresses_hint() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["missing_symbol", "--no-hint"])

    assert result.exit_code == 0
    assert "hint:" not in result.output


def test_search_path_query_shows_path_hint() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["Show Preview frontend/src"])

    assert result.exit_code == 0
    assert "path terms" in result.output


def test_search_empty_after_text_fallback_shows_files_searched() -> None:
    """When both symbol and text search ran but found nothing, hint shows files searched count."""
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "used_fallback": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
            "text_files_searched": 1504,
            "text_match_count": 0,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["xyznonexistent12345"])

    assert result.exit_code == 0
    assert "searched 1504 files" in result.output
    assert "st search --text" not in result.output


def test_search_text_fallback_shows_hint() -> None:
    payload = {
        "prompt_context": "Precision Code Search: text-fallback\n\n## Relevant Text Matches\n\n- file.py:1 - mode",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "used_fallback": True,
            "estimated_tokens_saved": 0,
            "final_tokens": 100,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["campaign mode"])

    assert result.exit_code == 0
    assert "fell back to text search" in result.output


def test_search_text_mode_calls_text_endpoint_and_renders_matches() -> None:
    payload = {
        "query": "special fallback token",
        "count": 1,
        "files_searched": 3,
        "items": [
            {
                "path": "backend/app/api/files.py",
                "line": 8,
                "content": '    marker = "special fallback token"',
                "language": "python",
            }
        ],
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["special fallback token", "--text"])

    assert result.exit_code == 0
    assert "SEARCH:special fallback token|mode=text|matches=1|files=3" in result.output
    assert "backend/app/api/files.py:8" in result.output
    assert "special fallback token" in result.output
    mock_client.return_value.get.assert_called_once_with(
        "http://testserver/explorer/text/search?q=special+fallback+token&limit=20"
    )


def test_search_file_mode_calls_file_symbols_endpoint() -> None:
    payload = {
        "file_path": "backend/app/api/explorer.py",
        "count": 2,
        "items": [
            {
                "qualified_name": "list_entries",
                "name": "list_entries",
                "kind": "function",
                "start_line": 37,
                "signature": "async def list_entries(project_id: str, ...)",
                "summary": "List explorer entries with filtering.",
            },
            {
                "qualified_name": "precision_search",
                "name": "precision_search",
                "kind": "function",
                "start_line": 97,
                "signature": "async def precision_search(project_id: str, ...)",
                "summary": "Full Precision Code Search.",
            },
        ],
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["dummy", "--file", "backend/app/api/explorer.py"])

    assert result.exit_code == 0
    assert "SEARCH:--file backend/app/api/explorer.py|mode=file-symbols|symbols=2" in result.output
    assert "`list_entries`" in result.output
    assert "`precision_search`" in result.output
    mock_client.return_value.get.assert_called_once()
    call_url = mock_client.return_value.get.call_args[0][0]
    assert "/explorer/symbols/by-file?" in call_url
    assert "file_path=backend" in call_url


def test_search_file_mode_empty_result() -> None:
    payload = {"file_path": "nonexistent.py", "count": 0, "items": []}

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["dummy", "--file", "nonexistent.py"])

    assert result.exit_code == 0
    assert "mode=empty" in result.output


def test_search_precision_passes_limit() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols",
        "metadata": {
            "symbol_count": 3,
            "used_symbol_first": True,
            "estimated_tokens_saved": 800,
            "final_tokens": 400,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["my_function", "--limit", "10"])

    assert result.exit_code == 0
    call_url = mock_client.return_value.get.call_args[0][0]
    assert "limit=10" in call_url
    assert "/explorer/precision-search?" in call_url


def test_search_precision_emits_delayed_status_note_for_slow_searches() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 500,
            "final_tokens": 200,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search._start_delayed_status_timer", side_effect=_immediate_status_timer),
    ):
        result = _invoke(["slow_symbol"])

    assert result.exit_code == 0
    assert "st search: still working;" in result.output
    assert "SEARCH:slow_symbol|mode=symbol-first|symbols=1|tokens=200|saved=500" in result.output


def test_search_precision_reports_completed_stale_refresh() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 500,
            "final_tokens": 200,
            "refreshed_index": True,
            "stale_hit": True,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["stale_symbol"])

    assert result.exit_code == 0
    assert "refreshed stale Explorer indexes before returning results" in result.output


def test_search_file_mode_scope_checkout_reads_local_symbols_without_api_even_with_project_override() -> None:
    with runner.isolated_filesystem():
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export function WorkspaceChatFooter() {\n  return null;\n}\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
            patch("cli.commands.search.STClient") as mock_client,
        ):
            result = _invoke(["dummy", "--file", str(file_path), "--scope", "checkout", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "SEARCH:--file frontend/src/example.tsx|mode=file-symbols|symbols=1|scope=checkout" in result.output
    assert "`WorkspaceChatFooter`" in result.output
    mock_client.assert_not_called()


def test_search_text_mode_scope_checkout_reads_local_matches_without_api() -> None:
    with runner.isolated_filesystem():
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export const label = 'Send steering instruction';\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
            patch("cli.commands.search.STClient") as mock_client,
        ):
            result = _invoke(["Send steering instruction", "--text", "--scope", "checkout"])

    assert result.exit_code == 0
    assert "SEARCH:Send steering instruction|mode=text|matches=1|files=1|scope=checkout" in result.output
    assert "frontend/src/example.tsx:1" in result.output
    mock_client.assert_not_called()


def test_search_scope_checkout_errors_when_no_checkout_root_exists() -> None:
    with (
        patch("cli.commands.search.resolve_checkout_root", return_value=None, create=True),
        patch("cli.commands.search.canonical_repo_root", return_value=None, create=True),
        patch("cli.commands.search.STClient") as mock_client,
    ):
        result = _invoke(["needle", "--scope", "checkout", "--json"])

    assert result.exit_code == 1
    assert "requires a git checkout" in result.output
    mock_client.assert_not_called()


def test_search_auto_scope_rootless_env_project_uses_checkout_when_local_project_matches() -> None:
    with runner.isolated_filesystem():
        Path(".index.yaml").write_text("project: summitflow\n", encoding="utf-8")
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export const label = 'local checkout token';\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": None, "project_id": "summitflow", "source": "env"})()),
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
            patch("cli.commands.search.STClient") as mock_client,
        ):
            result = _invoke(["local checkout token", "--text"])

    assert result.exit_code == 0
    assert "SEARCH:local checkout token|mode=text|matches=1" in result.output
    assert "|scope=checkout" in result.output
    mock_client.assert_not_called()


def test_search_auto_scope_rootless_env_project_does_not_mix_unrelated_checkout() -> None:
    payload = {"query": "local checkout token", "count": 0, "files_searched": 0, "items": []}

    with runner.isolated_filesystem():
        Path(".index.yaml").write_text("project: summitflow\n", encoding="utf-8")
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export const label = 'local checkout token';\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": None, "project_id": "agent-hub", "source": "env"})()),
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        ):
            result = _invoke(["local checkout token", "--text"])

    assert result.exit_code == 0
    assert "SEARCH:local checkout token|mode=empty|symbols=0|tokens=0" in result.output
    assert "scope=" not in result.output
    mock_client.return_value.get.assert_called_once()


def test_search_auto_scope_rootless_env_project_without_checkout_metadata_falls_back_to_project() -> None:
    payload = {"query": "local checkout token", "count": 0, "files_searched": 0, "items": []}

    with runner.isolated_filesystem():
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export const label = 'local checkout token';\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": None, "project_id": "agent-hub", "source": "env"})()),
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        ):
            result = _invoke(["local checkout token", "--text"])

    assert result.exit_code == 0
    assert "SEARCH:local checkout token|mode=empty|symbols=0|tokens=0" in result.output
    assert "scope=" not in result.output
    mock_client.return_value.get.assert_called_once()


def test_search_auto_scope_prepends_checkout_overrides_for_precision_results() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols\n\n- `WorkspaceChatFooter` (function) in frontend/src/example.tsx:1",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 100,
            "final_tokens": 40,
        },
    }

    with runner.isolated_filesystem():
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export function WorkspaceChatFooter() {\n  return 'latest checkout version';\n}\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client,
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        ):
            result = _invoke(["WorkspaceChatFooter", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "scope=combined" in result.output
    assert "## Current Checkout Overrides" in result.output
    assert "latest checkout version" in result.output
    mock_client.return_value.get.assert_called_once()


def test_search_auto_scope_maps_natural_language_queries_to_checkout_symbols() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
        },
    }

    with runner.isolated_filesystem():
        file_path = Path("frontend/src/project-selector.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export function ProjectSelector() {\n  return null;\n}\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        ):
            result = _invoke(["project selector", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "ProjectSelector" in result.output
    assert "scope=checkout" in result.output


def test_search_auto_scope_reapplies_budget_after_merging_checkout_and_project_context() -> None:
    repeated_project_context = " ".join(["project"] * 200)
    payload = {
        "prompt_context": repeated_project_context,
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 100,
            "final_tokens": 200,
        },
    }

    with runner.isolated_filesystem():
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export function WorkspaceChatFooter() {\n  return 'checkout checkout checkout checkout checkout';\n}\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        ):
            result = _invoke(["WorkspaceChatFooter", "--project", "summitflow", "--json", "--budget", "20"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["metadata"]["scope"] == "combined"
    assert parsed["metadata"]["final_tokens"] <= 20


def test_search_combined_scope_uses_checkout_leading_mode_in_compact_output() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols\n\n- `IndexedSymbol` (function) in backend/app/indexed.py:1",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 100,
            "final_tokens": 40,
        },
    }

    with runner.isolated_filesystem():
        file_path = Path("frontend/src/example.tsx")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            "export const label = 'special checkout marker';\n",
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
            patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        ):
            result = _invoke(["special checkout marker", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "SEARCH:special checkout marker|mode=text-fallback" in result.output
    assert "## Current Checkout Matches" in result.output
