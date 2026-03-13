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
