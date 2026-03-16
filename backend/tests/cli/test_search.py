"""Tests for `st search` CLI behavior."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from cli.commands.search import app

runner = CliRunner()


def _mock_client(result: dict[str, object]) -> MagicMock:
    client = MagicMock()
    client._url.side_effect = lambda path: f"http://testserver{path}"
    client.get.return_value = result
    return client


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
        result = runner.invoke(app, ["proxy_complete"])

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
        result = runner.invoke(app, ["proxy_complete", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload


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
        result = runner.invoke(app, ["missing_symbol"])

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
        result = runner.invoke(app, ["missing_symbol"])

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
        result = runner.invoke(app, ["missing_symbol", "--no-hint"])

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
        result = runner.invoke(app, ["Show Preview frontend/src"])

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
        result = runner.invoke(app, ["xyznonexistent12345"])

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
        result = runner.invoke(app, ["campaign mode"])

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
        result = runner.invoke(app, ["special fallback token", "--text"])

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
        result = runner.invoke(app, ["dummy", "--file", "backend/app/api/explorer.py"])

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
        result = runner.invoke(app, ["dummy", "--file", "nonexistent.py"])

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
        result = runner.invoke(app, ["my_function", "--limit", "10"])

    assert result.exit_code == 0
    call_url = mock_client.return_value.get.call_args[0][0]
    assert "limit=10" in call_url
    assert "/explorer/precision-search?" in call_url
