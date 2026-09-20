"""Design extension wrapper tests; domain behavior belongs to design-tools."""

from __future__ import annotations

import subprocess
from typing import Any

from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


def test_design_wrapper_forwards_exact_owner_argv(monkeypatch: Any) -> None:
    """The generic ST wrapper must pass the owner command through unchanged."""
    extension_context = {
        "contract_version": 1,
        "project_id": "monkey-fight",
        "project_root": "/projects/monkey-fight",
        "cwd": "/workspace",
        "api_base": "http://localhost:8001/api",
        "agent_hub_url": "http://localhost:8003",
        "output": {"human": False, "compact": True, "progress_only": False},
    }
    observed: list[tuple[Any, list[str], dict[str, Any]]] = []

    monkeypatch.setattr("cli.extensions.extension_context", lambda _output: extension_context)
    monkeypatch.setattr(
        "cli.extensions.dispatch_extension",
        lambda record, argv, **kwargs: observed.append((record, argv, kwargs)) or 0,
    )
    owner_argv = [
        "asset",
        "generate",
        "Kiki attack sheet",
        "Capuchin fighter combo sheet",
        "--agent-hub-fallback",
        "--tags",
        "kiki,combat",
    ]

    result = runner.invoke(app, ["design", *owner_argv])

    assert result.exit_code == 0, result.output
    assert len(observed) == 1
    record, argv, kwargs = observed[0]
    assert record.binding is not None
    assert record.binding.id == "design-tools.design"
    assert argv == owner_argv
    assert kwargs["context"] is extension_context


def test_design_nested_help_is_static_and_never_executes(monkeypatch: Any) -> None:
    """Nested help comes from trusted metadata, not the owner executable."""
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("static design help attempted runtime execution")

    monkeypatch.setattr("cli.extensions.extension_context", forbidden)
    monkeypatch.setattr("cli.extensions.dispatch_extension", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    result = runner.invoke(
        app,
        ["design", "asset", "generate", "Kiki attack sheet", "brief", "--help"],
    )

    assert result.exit_code == 0, result.output
    assert "Usage: st design asset generate" in result.output
    assert "--agent-hub-fallback" in result.output
