"""Tests for refactor task CLI commands."""

from __future__ import annotations

from typing import Any, ClassVar
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands.refactor import app

runner = CliRunner()


class _FakeSTClient:
    instances: ClassVar[list[_FakeSTClient]] = []

    def __init__(self, *args: object, timeout: float | None = 330.0, **kwargs: object) -> None:
        self.timeout = timeout
        self.project_id = "summitflow"
        self.calls: list[dict[str, object]] = []
        _FakeSTClient.instances.append(self)

    def _url(self, path: str) -> str:
        return f"http://summitflow.test/api/projects/{self.project_id}{path}"

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"url": url, "json": json, "params": params})
        if params == {"sync": "true"}:
            return {
                "status": "completed",
                "project_id": self.project_id,
                "closed_count": 1,
                "created_count": 2,
                "scanned_count": 3,
            }
        return {"status": "started", "project_id": self.project_id}


def test_refactor_regenerate_dispatches_background_by_default() -> None:
    _FakeSTClient.instances.clear()

    with patch("cli.commands.refactor.STClient", _FakeSTClient):
        result = runner.invoke(app)

    assert result.exit_code == 0
    assert "REFACTOR_SYNC: status=started project=summitflow" in result.output
    client = _FakeSTClient.instances[0]
    assert client.calls[0]["params"] is None


def test_refactor_regenerate_sync_requires_explicit_flag_and_no_client_timeout() -> None:
    _FakeSTClient.instances.clear()

    with patch("cli.commands.refactor.STClient", _FakeSTClient):
        result = runner.invoke(app, ["--sync"])

    assert result.exit_code == 0
    assert "REFACTOR_SYNC: closed=1 created=2 scanned=3" in result.output
    client = _FakeSTClient.instances[0]
    assert client.timeout is None
    assert client.calls[0]["params"] == {"sync": "true"}
