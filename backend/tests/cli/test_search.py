"""Search extension wrapper tests; domain behavior belongs to code-intelligence."""

from __future__ import annotations

import subprocess
from typing import Any

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_search_wrapper_forwards_exact_owner_argv(monkeypatch: Any) -> None:
    """The generic ST wrapper must pass search arguments through unchanged."""
    context = {
        "contract_version": 1,
        "project_id": "summitflow",
        "project_root": "/projects/summitflow",
        "cwd": "/workspace",
        "api_base": "http://localhost:8001/api",
        "agent_hub_url": "http://localhost:8003",
        "output": {"human": False, "compact": True, "progress_only": False},
    }
    observed: list[tuple[Any, list[str], dict[str, Any]]] = []
    monkeypatch.setattr("cli.extensions.extension_context", lambda _output: context)
    monkeypatch.setattr(
        "cli.extensions.dispatch_extension",
        lambda record, argv, **kwargs: observed.append((record, argv, kwargs)) or 0,
    )
    owner_argv = ["proxy_complete", "--scope", "project", "--limit", "7", "--json"]

    result = runner.invoke(app, ["search", *owner_argv])

    assert result.exit_code == 0, result.output
    assert len(observed) == 1
    record, argv, kwargs = observed[0]
    assert record.binding is not None
    assert record.binding.id == "code-intelligence.search"
    assert argv == owner_argv
    assert kwargs["context"] is context


def test_search_help_is_static_and_never_executes(monkeypatch: Any) -> None:
    """Search help comes from trusted metadata, not the owner executable."""
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("static search help attempted runtime execution")

    monkeypatch.setattr("cli.extensions.extension_context", forbidden)
    monkeypatch.setattr("cli.extensions.dispatch_extension", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = runner.invoke(app, ["search", "proxy_complete", "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage: st search" in result.output
    assert "--scope" in result.output
