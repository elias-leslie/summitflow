"""Graph extension wrapper tests; domain behavior belongs to code-intelligence."""

from __future__ import annotations

import subprocess
from typing import Any

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_graph_wrapper_forwards_exact_owner_argv(monkeypatch: Any) -> None:
    """The generic ST wrapper must pass graph arguments through unchanged."""
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
    owner_argv = ["query", "central modules?", "--budget", "900", "--dfs"]

    result = runner.invoke(app, ["graph", *owner_argv])

    assert result.exit_code == 0, result.output
    assert len(observed) == 1
    record, argv, kwargs = observed[0]
    assert record.binding is not None
    assert record.binding.id == "code-intelligence.graph"
    assert argv == owner_argv
    assert kwargs["context"] is context


def test_graph_nested_help_is_static_and_never_executes(monkeypatch: Any) -> None:
    """Nested graph help comes from trusted metadata, not the owner executable."""
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("static graph help attempted runtime execution")

    monkeypatch.setattr("cli.extensions.extension_context", forbidden)
    monkeypatch.setattr("cli.extensions.dispatch_extension", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = runner.invoke(app, ["graph", "query", "central modules?", "--help"])

    assert result.exit_code == 0, result.output
    assert "Usage: st graph query" in result.output
    assert "--budget" in result.output
