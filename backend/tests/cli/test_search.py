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
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
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
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
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


def test_search_caps_limit_above_api_max() -> None:
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
        result = _invoke(["my_function", "--limit", "30"])

    assert result.exit_code == 0
    call_url = mock_client.return_value.get.call_args[0][0]
    assert "limit=20" in call_url
    assert "st search: --limit 30 capped at 20." in result.output


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


def test_search_precision_suppresses_stale_warning_when_results_returned() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 500,
            "final_tokens": 200,
            "refreshed_index": False,
            "stale_hit": True,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["stale_symbol"])

    assert result.exit_code == 0
    assert "Explorer indexes are stale" not in result.output
    assert "SEARCH:stale_symbol|mode=symbol-first|symbols=1|tokens=200|saved=500" in result.output


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


def test_search_text_mode_checkout_path_file_treats_pipe_as_literal() -> None:
    with runner.isolated_filesystem():
        file_path = Path("backend/cli/example.py")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            'line = "HARNESS:{mode}|reasons:{reason_text}"\n',
            encoding="utf-8",
        )

        with (
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
            patch("cli.commands.search.STClient") as mock_client,
        ):
            result = _invoke([
                "HARNESS:{mode}|reasons",
                "--text",
                "--scope",
                "checkout",
                "--path",
                "backend/cli/example.py",
            ])

    assert result.exit_code == 0
    assert "SEARCH:HARNESS:{mode}|reasons|mode=text|matches=1|files=1|scope=checkout|path=backend/cli/example.py" in result.output
    assert "backend/cli/example.py:1" in result.output
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


def test_search_precision_path_option_calls_precision_endpoint_with_path_prefix() -> None:
    payload = {
        "query": "transition-all",
        "prompt_context": "Precision Code Search: text-fallback",
        "metadata": {"symbol_count": 0, "used_symbol_first": False, "path_prefix": "packages/notes-ui"},
    }

    with patch("cli.commands.search.STClient", return_value=_mock_client(payload)) as mock_client:
        result = _invoke(["transition-all", "--path", "packages/notes-ui", "--project", "summitflow", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    mock_client.return_value.get.assert_called_once_with(
        "http://testserver/explorer/precision-search?q=transition-all&budget=1200&limit=20&path_prefix=packages%2Fnotes-ui"
    )


def test_search_auto_scope_skips_checkout_overlay_when_checkout_is_clean() -> None:
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols\n\n- `WorkspaceChatFooter`",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 100,
            "final_tokens": 40,
        },
    }

    with (
        runner.isolated_filesystem(),
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
        patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        patch("cli.commands.search._checkout_has_local_changes", return_value=False),
    ):
        result = _invoke(["WorkspaceChatFooter", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "scope=combined" not in result.output
    assert "## Current Checkout Overrides" not in result.output
    assert "WorkspaceChatFooter" in result.output


def test_search_text_fallback_definition_match_shows_stale_index_hint() -> None:
    payload = {
        "prompt_context": "Precision Code Search: text-fallback\n\n## Relevant Text Matches\n\n- check_execution.py:61 - def tool_not_installed(",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "used_fallback": True,
            "definition_matched_terms": ["tool_not_installed"],
            "symbol_index_age_minutes": 40216,
            "estimated_tokens_saved": 0,
            "final_tokens": 100,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value="summitflow", create=True),
        patch("cli.commands.search.get_project_root_path", return_value=None),
    ):
        result = _invoke(["tool_not_installed", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "definition of `tool_not_installed` that the symbol index missed" in result.output
    assert "index age 40216m" in result.output
    assert "--scope checkout" in result.output
    assert "Try a specific identifier" not in result.output


def test_search_text_fallback_definition_match_after_empty_escalation_recommends_rescan_only() -> None:
    """Definition-stale signal plus an already-empty live parse: recommend a
    rescan, never a futile `--scope checkout` rerun."""
    payload = {
        "prompt_context": "Precision Code Search: text-fallback\n\n## Relevant Text Matches\n\n- check_execution.py:61 - def tool_not_installed(",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "used_fallback": True,
            "definition_matched_terms": ["tool_not_installed"],
            "symbol_index_age_minutes": 40216,
            "estimated_tokens_saved": 0,
            "final_tokens": 100,
        },
    }
    checkout_empty = {
        "query": "tool_not_installed",
        "prompt_context": "",
        "metadata": {"scope": "checkout", "symbol_count": 0, "used_symbol_first": False, "used_fallback": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, checkout_empty):
            stack.enter_context(p)
        result = runner.invoke(app, ["tool_not_installed"])

    assert result.exit_code == 0
    assert "live checkout parse also found no symbol" in result.output
    assert "--scope checkout" not in result.output


def _escalation_patches(payload: Mapping[str, Any], checkout_result: Mapping[str, Any] | None):
    patches = [
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value="summitflow", create=True),
        patch("cli.commands.search._checkout_has_local_changes", return_value=False),
    ]
    if checkout_result is not None:
        patches.append(patch("cli.commands.search._build_checkout_precision_result", return_value=checkout_result))
    return patches


def test_search_auto_scope_escalates_to_checkout_when_index_misses_identifier() -> None:
    """Stale canonical symbol index: identifier query with zero indexed symbols
    must fall through to live checkout symbol parsing without --scope checkout."""
    payload = {
        "prompt_context": "",
        "metadata": {"symbol_count": 0, "used_symbol_first": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }
    checkout_result = {
        "query": "tool_not_installed",
        "prompt_context": "## Current Checkout Overrides\n\n- `tool_not_installed` (function) in backend/cli/commands/check_execution.py:61",
        "metadata": {"scope": "checkout", "checkout_root": "/srv/workspaces/projects/summitflow", "symbol_count": 1, "used_symbol_first": True, "used_fallback": False, "estimated_tokens_saved": 0, "final_tokens": 30},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, checkout_result):
            stack.enter_context(p)
        result = runner.invoke(app, ["tool_not_installed"])

    assert result.exit_code == 0
    assert "## Current Checkout Overrides" in result.output
    assert "symbols=1" in result.output
    assert "prepended current checkout results" in result.output


def test_search_auto_scope_does_not_escalate_for_prose_query() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {"symbol_count": 0, "used_symbol_first": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, None):
            stack.enter_context(p)
        build_mock = stack.enter_context(
            patch("cli.commands.search._build_checkout_precision_result")
        )
        result = runner.invoke(app, ["campaign mode"])

    assert result.exit_code == 0
    build_mock.assert_not_called()


def test_search_auto_scope_other_project_override_escalates_to_target_project_root(tmp_path: Path) -> None:
    """Cross-project identifier miss escalates to the *target* project's
    registered root for live parsing — never the local cwd checkout."""
    payload = {
        "prompt_context": "",
        "metadata": {"symbol_count": 0, "used_symbol_first": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }
    checkout_result = {
        "query": "tool_not_installed",
        "prompt_context": "## Current Checkout Overrides\n\n- `tool_not_installed` (function) in src/check.py:6",
        "metadata": {"scope": "checkout", "checkout_root": str(tmp_path), "symbol_count": 1, "used_symbol_first": True, "used_fallback": False, "estimated_tokens_saved": 0, "final_tokens": 30},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, None):
            stack.enter_context(p)
        build_mock = stack.enter_context(
            patch("cli.commands.search._build_checkout_precision_result", return_value=checkout_result)
        )
        stack.enter_context(patch("cli.commands.search.get_project_root_path", return_value=str(tmp_path)))
        result = runner.invoke(app, ["tool_not_installed", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "## Current Checkout Overrides" in result.output
    assert "symbols=1" in result.output
    assert build_mock.call_args.args[1] == tmp_path


def test_search_auto_scope_other_project_override_without_registered_root_does_not_parse_local_tree() -> None:
    """No registered root for the target project: never fall back to parsing
    the unrelated local checkout."""
    payload = {
        "prompt_context": "",
        "metadata": {"symbol_count": 0, "used_symbol_first": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, None):
            stack.enter_context(p)
        build_mock = stack.enter_context(
            patch("cli.commands.search._build_checkout_precision_result")
        )
        stack.enter_context(patch("cli.commands.search.get_project_root_path", return_value=None))
        result = runner.invoke(app, ["tool_not_installed", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "mode=empty" in result.output
    build_mock.assert_not_called()


def _cross_project_scope_checkout_patches() -> list[Any]:
    return [
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value="summitflow", create=True),
        patch("cli.commands.search.get_config_optional", return_value=type("Cfg", (), {"project_root": "/srv/workspaces/projects/summitflow", "project_id": "summitflow"})()),
        patch("cli.commands.search._checkout_has_local_changes", return_value=False),
    ]


def test_search_scope_checkout_cross_project_searches_target_root_not_cwd(tmp_path: Path) -> None:
    """`-P <other-project> --scope checkout` must search the target project's
    registered root, never the unrelated tree the agent happens to stand in."""
    target_file = tmp_path / "src" / "remote.py"
    target_file.parent.mkdir(parents=True)
    target_file.write_text("def qqzz_cross_project_symbol():\n    return 1\n", encoding="utf-8")

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _cross_project_scope_checkout_patches():
            stack.enter_context(p)
        root_mock = stack.enter_context(patch("cli.commands.search.get_project_root_path", return_value=str(tmp_path)))
        mock_client = stack.enter_context(patch("cli.commands.search.STClient"))
        result = runner.invoke(app, ["qqzz_cross_project_symbol", "--text", "--scope", "checkout", "--project", "agent-hub"])

    assert result.exit_code == 0
    assert "src/remote.py:1" in result.output
    assert "scope=checkout" in result.output
    root_mock.assert_called_once_with("agent-hub")
    mock_client.assert_not_called()


def test_search_scope_checkout_cross_project_without_registered_root_errors() -> None:
    """No registered root for the target project: fail with a precise error
    instead of silently returning wrong-project results from the cwd tree."""
    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _cross_project_scope_checkout_patches():
            stack.enter_context(p)
        stack.enter_context(patch("cli.commands.search.get_project_root_path", return_value=None))
        mock_client = stack.enter_context(patch("cli.commands.search.STClient"))
        result = runner.invoke(app, ["qqzz_cross_project_symbol", "--text", "--scope", "checkout", "--project", "agent-hub"])

    assert result.exit_code == 1
    assert "needs a local root for project `agent-hub`" in result.output
    mock_client.assert_not_called()


def test_search_auto_scope_escalation_keeps_project_result_when_checkout_finds_nothing() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {"symbol_count": 0, "used_symbol_first": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }
    checkout_empty = {
        "query": "missing_thing",
        "prompt_context": "",
        "metadata": {"scope": "checkout", "symbol_count": 0, "used_symbol_first": False, "used_fallback": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, checkout_empty):
            stack.enter_context(p)
        result = runner.invoke(app, ["missing_thing"])

    assert result.exit_code == 0
    assert "mode=empty" in result.output
    assert "## Current Checkout Overrides" not in result.output


def test_search_hint_drops_scope_checkout_advice_after_empty_escalation() -> None:
    """When the live checkout was already parsed and had nothing, the hint
    must not recommend a futile `--scope checkout` rerun."""
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
            "missed_identifier_terms": ["missing_thing"],
        },
    }
    checkout_empty = {
        "query": "missing_thing",
        "prompt_context": "",
        "metadata": {"scope": "checkout", "symbol_count": 0, "used_symbol_first": False, "used_fallback": False, "estimated_tokens_saved": 0, "final_tokens": 0},
    }

    from contextlib import ExitStack

    with ExitStack() as stack:
        for p in _escalation_patches(payload, checkout_empty):
            stack.enter_context(p)
        result = runner.invoke(app, ["missing_thing"])

    assert result.exit_code == 0
    assert "live parse of the checkout found no definition" in result.output
    assert "--scope checkout" not in result.output


def test_search_hint_keeps_scope_checkout_advice_when_escalation_did_not_run() -> None:
    """Without an escalation attempt the brand-new-code advice stays."""
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
            "missed_identifier_terms": ["missing_thing"],
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
    ):
        result = _invoke(["missing_thing"])

    assert result.exit_code == 0
    assert "rerun with `--scope checkout` or rescan the project" in result.output


def test_search_empty_missed_identifier_shows_identifier_hint() -> None:
    """A nonexistent identifier must produce a verify-the-name hint, not generic advice."""
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
            "text_files_searched": 2012,
            "missed_identifier_terms": ["resolve_search_timeout"],
            "suppressed_generic_symbols": 17,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
    ):
        result = _invoke(["resolve_search_timeout handler"])

    assert result.exit_code == 0
    assert "`resolve_search_timeout` matched no symbols or text" in result.output
    assert "17 symbols matching only the other words were withheld" in result.output


def test_search_symbol_first_partial_missed_identifier_hint() -> None:
    """When one identifier hit and another missed, the hint names the missed one."""
    payload = {
        "prompt_context": "Precision Code Search: symbol-first\n\n## Relevant Symbols",
        "metadata": {
            "symbol_count": 3,
            "used_symbol_first": True,
            "estimated_tokens_saved": 100,
            "final_tokens": 50,
            "missed_identifier_terms": ["missing_helper"],
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
    ):
        result = _invoke(["scan_all_projects missing_helper"])

    assert result.exit_code == 0
    assert "`missing_helper` matched nothing" in result.output


def test_search_missed_identifier_hint_suppressed_when_checkout_overlay_applied() -> None:
    """Checkout overlay means fresh code answered the query; the missed-index hint would mislead."""
    payload = {
        "prompt_context": "## Current Checkout Overrides\n\n- `resolve_search_timeout`",
        "metadata": {
            "symbol_count": 1,
            "used_symbol_first": True,
            "estimated_tokens_saved": 0,
            "final_tokens": 50,
            "missed_identifier_terms": ["resolve_search_timeout"],
            "checkout_overlay_applied": True,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
    ):
        result = _invoke(["resolve_search_timeout"])

    assert result.exit_code == 0
    assert "matched nothing" not in result.output
    assert "matched no symbols or text" not in result.output


def test_search_stale_age_only_warning_does_not_claim_failed_refresh() -> None:
    """Age-based staleness never attempts a refresh, so the warning must not say one failed."""
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
            "stale_hit": True,
            "refreshed_index": False,
            "refresh_reasons": ["stale_symbol_index", "stale_file_index"],
            "symbol_index_age_minutes": 95,
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
    ):
        result = _invoke(["stale_symbol"])

    assert result.exit_code == 0
    assert "refresh did not complete" not in result.output
    assert "(95m old)" in result.output
    assert "predates the latest scheduled scan" in result.output


def test_search_stale_missing_index_keeps_failed_refresh_warning() -> None:
    payload = {
        "prompt_context": "",
        "metadata": {
            "symbol_count": 0,
            "used_symbol_first": False,
            "estimated_tokens_saved": 0,
            "final_tokens": 0,
            "stale_hit": True,
            "refreshed_index": False,
            "refresh_reasons": ["missing_symbol_index"],
        },
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
        patch("cli.commands.search.resolve_checkout_project_id", return_value=None, create=True),
    ):
        result = _invoke(["stale_symbol"])

    assert result.exit_code == 0
    assert "refresh did not complete" in result.output


def test_without_generic_only_items_drops_junk_when_identifier_missed() -> None:
    from cli.lib.search_checkout_symbols import _without_generic_only_items

    junk = [
        {"name": "handler", "qualified_name": "useMediaQuery.handler", "file_path": "frontend/hooks/useMediaQuery.ts"},
        {"name": "setup_exception_handlers", "qualified_name": "setup_exception_handlers", "file_path": "backend/app/exception_handlers.py"},
    ]
    assert _without_generic_only_items(junk, "resolve_search_timeout handler") == []


def test_without_generic_only_items_keeps_items_when_identifier_covered() -> None:
    from cli.lib.search_checkout_symbols import _without_generic_only_items

    items = [
        {"name": "handler", "qualified_name": "useMediaQuery.handler", "file_path": "frontend/hooks/useMediaQuery.ts"},
        {"name": "resolve_search_timeout", "qualified_name": "resolve_search_timeout", "file_path": "backend/app/search.py"},
    ]
    assert _without_generic_only_items(items, "resolve_search_timeout handler") == items


def test_without_generic_only_items_counts_case_variant_as_coverage() -> None:
    from cli.lib.search_checkout_symbols import _without_generic_only_items

    items = [{"name": "ResolveSearchTimeout", "qualified_name": "ResolveSearchTimeout", "file_path": "frontend/lib/search.ts"}]
    assert _without_generic_only_items(items, "resolve_search_timeout") == items


def test_without_generic_only_items_no_identifier_tokens_keeps_items() -> None:
    from cli.lib.search_checkout_symbols import _without_generic_only_items

    items = [{"name": "handler", "qualified_name": "handler", "file_path": "frontend/hooks/useMediaQuery.ts"}]
    assert _without_generic_only_items(items, "project selector") == items


def test_search_file_mode_empty_shows_not_found_hint() -> None:
    payload = {"file_path": "qqzz_missing.py", "count": 0, "items": []}

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["dummy", "--file", "qqzz_missing.py"])

    assert result.exit_code == 0
    assert "mode=empty" in result.output
    assert "hint: no file matching `qqzz_missing.py` found" in result.output


def test_search_file_mode_ambiguous_fragment_lists_candidates() -> None:
    payload = {
        "file_path": "utils.py",
        "count": 0,
        "items": [],
        "candidates": ["backend/app/utils.py", "backend/cli/utils.py"],
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["dummy", "--file", "utils.py"])

    assert result.exit_code == 0
    assert "hint: `utils.py` matches multiple files" in result.output
    assert "`backend/app/utils.py`" in result.output
    assert "`backend/cli/utils.py`" in result.output


def test_search_file_mode_resolved_basename_notes_resolution() -> None:
    payload = {
        "file_path": "backend/app/api/files.py",
        "resolved_from": "files.py",
        "count": 1,
        "items": [
            {
                "qualified_name": "get_file_tree",
                "name": "get_file_tree",
                "kind": "function",
                "start_line": 24,
                "signature": "def get_file_tree(path: str) -> dict",
            }
        ],
    }

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["dummy", "--file", "files.py"])

    assert result.exit_code == 0
    assert (
        "SEARCH:--file backend/app/api/files.py|mode=file-symbols|symbols=1|resolved_from=files.py"
        in result.output
    )
    assert "`get_file_tree`" in result.output


def test_search_file_mode_existing_file_without_symbols_hint() -> None:
    payload = {"file_path": "README.md", "count": 0, "items": [], "file_exists": True}

    with (
        patch("cli.commands.search.STClient", return_value=_mock_client(payload)),
        patch("cli.commands.search.is_compact", return_value=True),
    ):
        result = _invoke(["dummy", "--file", "README.md"])

    assert result.exit_code == 0
    assert "hint: `README.md` has no extractable symbols" in result.output


def test_search_file_mode_scope_checkout_resolves_basename() -> None:
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
            result = _invoke(["dummy", "--file", "example.tsx", "--scope", "checkout"])

    assert result.exit_code == 0
    assert (
        "SEARCH:--file frontend/src/example.tsx|mode=file-symbols|symbols=1|scope=checkout|resolved_from=example.tsx"
        in result.output
    )
    assert "`WorkspaceChatFooter`" in result.output
    mock_client.assert_not_called()


def test_search_file_mode_scope_checkout_ambiguous_lists_candidates() -> None:
    with runner.isolated_filesystem():
        for parent in ("frontend/src", "frontend/widgets"):
            file_path = Path(parent) / "example.tsx"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("export const x = 1;\n", encoding="utf-8")

        with (
            patch("cli.commands.search.is_compact", return_value=True),
            patch("cli.commands.search.resolve_checkout_root", return_value=Path.cwd(), create=True),
            patch("cli.commands.search.canonical_repo_root", return_value=Path("/srv/workspaces/projects/summitflow"), create=True),
            patch("cli.commands.search.STClient") as mock_client,
        ):
            result = _invoke(["dummy", "--file", "example.tsx", "--scope", "checkout"])

    assert result.exit_code == 0
    assert "mode=empty" in result.output
    assert "hint: `example.tsx` matches multiple files" in result.output
    assert "`frontend/src/example.tsx`" in result.output
    assert "`frontend/widgets/example.tsx`" in result.output
    mock_client.assert_not_called()
