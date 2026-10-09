"""Prompt templates are fetched through the SDK ``get_prompt`` method."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import httpx
import pytest
from agent_hub.exceptions import AgentHubError, ServerError

from app.tasks.autonomous.exec_modules import _prompt_fetch


@pytest.fixture
def client(mocker) -> Iterator[MagicMock]:
    _prompt_fetch._prompt_cache.clear()
    sdk = MagicMock()
    sdk.__enter__.return_value = sdk
    mocker.patch.object(_prompt_fetch, "get_sync_client", return_value=sdk)
    mocker.patch.object(_prompt_fetch, "sleep")
    yield sdk
    _prompt_fetch._prompt_cache.clear()


def test_fetch_retries_transient_failures_then_caches(client: MagicMock) -> None:
    client.get_prompt.side_effect = [
        httpx.ConnectError("refused"),
        ServerError("Server error: restarting", status_code=503),
        {"slug": "autocode-x", "content": "Do {thing}"},
    ]

    assert _prompt_fetch.get_prompt_template("autocode-x") == "Do {thing}"
    assert _prompt_fetch.get_prompt_template("autocode-x") == "Do {thing}"
    assert client.get_prompt.call_count == 3
    client.get_prompt.assert_called_with("autocode-x")


def test_fetch_exhausting_retries_is_transient(client: MagicMock) -> None:
    client.get_prompt.side_effect = httpx.ConnectError("refused")

    with pytest.raises(_prompt_fetch.TransientPromptFetchError):
        _prompt_fetch.get_prompt_template("autocode-x")
    assert client.get_prompt.call_count == _prompt_fetch._MAX_FETCH_ATTEMPTS


def test_missing_or_empty_prompt_is_not_transient(client: MagicMock) -> None:
    client.get_prompt.side_effect = AgentHubError("Request failed: not found", status_code=404)
    with pytest.raises(_prompt_fetch.PromptFetchError) as missing:
        _prompt_fetch.get_prompt_template("absent")
    assert not isinstance(missing.value, _prompt_fetch.TransientPromptFetchError)
    assert client.get_prompt.call_count == 1

    client.get_prompt.side_effect = None
    client.get_prompt.return_value = {"slug": "empty", "content": ""}
    with pytest.raises(_prompt_fetch.PromptFetchError, match="empty content"):
        _prompt_fetch.get_prompt_template("empty")
