"""Regression tests for the public, application-neutral ST extension SDK."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import typer


def test_import_isolated_from_foreign_app_namespace(tmp_path: Path) -> None:
    """The SDK must not accidentally resolve through an owner's ``app`` package."""
    (tmp_path / "app.py").write_text("sentinel = 'foreign-owner'\n", encoding="utf-8")
    package_root = Path(__file__).parents[3] / "packages" / "st-sdk"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(tmp_path), str(package_root)))
    script = """
import app
assert app.sentinel == 'foreign-owner'
import st_sdk
import st_sdk.config
import st_sdk.project_client
assert not any(name.startswith('app.') for name in __import__('sys').modules)
assert not any(name == 'cli' or name.startswith('cli.') for name in __import__('sys').modules)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_run_app_applies_extension_context_before_callback(
    monkeypatch, tmp_path: Path
) -> None:
    from st_sdk import config, state
    from st_sdk.context import OutputContext
    from st_sdk.runtime import clear_context, run_app

    caller_cwd = tmp_path / "foreign-checkout"
    selected_root = tmp_path / "selected-project"
    caller_cwd.mkdir()
    selected_root.mkdir()
    monkeypatch.chdir(caller_cwd)
    monkeypatch.setenv(
        "ST_EXTENSION_CONTEXT",
        json.dumps(
            {
                "contract_version": 1,
                "project_id": "selected-project",
                "project_root": str(selected_root),
                "cwd": str(caller_cwd),
                "api_base": "http://summitflow.test/api",
                "agent_hub_url": "http://agent-hub.test",
                "output": {"human": True, "compact": False, "progress_only": False},
            }
        ),
    )
    observed: dict[str, object] = {}
    app = typer.Typer()

    @app.callback()
    def root() -> None:
        pass

    @app.command()
    def inspect(ctx: typer.Context) -> None:
        cfg = config.get_config()
        observed.update(
            project_id=cfg.project_id,
            project_root=cfg.project_root,
            source=cfg.source,
            cwd=Path.cwd(),
            output=ctx.obj,
            human=state.is_human(),
            compact=state.is_compact(),
            progress_only=state.is_progress_only(),
        )

    try:
        with pytest.raises(SystemExit) as exc_info:
            run_app(app, "owner", args=["inspect"])
        assert exc_info.value.code == 0
    finally:
        clear_context()

    assert observed == {
        "project_id": "selected-project",
        "project_root": str(selected_root),
        "source": "context",
        "cwd": caller_cwd,
        "output": OutputContext(human=True, compact=False, progress_only=False),
        "human": True,
        "compact": False,
        "progress_only": False,
    }


def test_selected_project_config_resolves_registered_root(tmp_path: Path) -> None:
    selected_root = tmp_path / "selected-project"
    selected_root.mkdir()
    package_root = Path(__file__).parents[3] / "packages" / "st-sdk"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root)
    script = f"""
import json
import httpx
from st_sdk import config

requests = []
def registered_projects(url, **kwargs):
    requests.append(url)
    return httpx.Response(200, json=[{{
        "id": "selected-project",
        "root_path": {str(selected_root)!r},
    }}])

config.httpx.get = registered_projects
config.set_project_override("selected-project")
resolved = config.get_config_optional()
print(json.dumps({{
    "project_id": resolved.project_id,
    "project_root": resolved.project_root,
    "source": resolved.source,
    "requests": requests,
}}))
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "project_id": "selected-project",
        "project_root": str(selected_root),
        "source": "flag",
        "requests": ["http://localhost:8001/api/projects"],
    }


def test_selected_project_override_is_lazy_during_static_description(tmp_path: Path) -> None:
    package_root = Path(__file__).parents[3] / "packages" / "st-sdk"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(package_root)
    script = """
import typer
from st_sdk import config
from st_sdk.runtime import describe_app

def forbidden(*args, **kwargs):
    raise AssertionError("static description contacted the project registry")

config.httpx.get = forbidden
config.set_project_override("selected-project")
app = typer.Typer(help="Static owner help")
@app.callback()
def root():
    pass
print(describe_app(app, "owner")["help"][""])
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Static owner help" in result.stdout


def test_describe_app_returns_complete_static_help_and_usage() -> None:
    from st_sdk.runtime import describe_app
    from st_sdk.usage import usage

    app = typer.Typer(help="Owner root help")
    nested = typer.Typer(help="Nested help")
    app.add_typer(nested, name="sub")

    @nested.command("work", help="Do owner work")
    @usage(surface="st.owner.work", cmd="st owner sub work")
    def work(
        item: str = typer.Argument(..., help="Item to process"),
        count: int = typer.Option(2, "--count", help="Number of passes"),
    ) -> None:
        _ = (item, count)
        raise AssertionError("description must not execute callbacks")

    description = describe_app(app, "owner")

    assert description["namespace"] == "owner"
    assert set(description["help"]) == {"", "sub", "sub work"}
    assert "Owner root help" in description["help"][""]
    assert "Nested help" in description["help"]["sub"]
    assert "Do owner work" in description["help"]["sub work"]
    assert "ITEM" in description["help"]["sub work"]
    assert "--count" in description["help"]["sub work"]
    assert "Number of passes" in description["help"]["sub work"]
    assert description["usage"] == [
        {
            "surface": "st.owner.work",
            "tier": "reference",
            "cmd": "st owner sub work",
        }
    ]


def test_usage_walker_supports_static_multi_surface_callbacks() -> None:
    from st_sdk.usage import UsageSpec, collect_usage_specs

    app = typer.Typer()

    def dispatch() -> None:
        pass

    dispatch.__st_usage_specs__ = [  # type: ignore[attr-defined]
        UsageSpec(surface="st.owner.one"),
        UsageSpec(surface="st.owner.two", tier="guardrail"),
    ]
    app.command("dispatch")(dispatch)

    assert [spec.surface for spec in collect_usage_specs(app)] == [
        "st.owner.one",
        "st.owner.two",
    ]


@pytest.mark.parametrize(
    ("args", "expected_status"),
    [(["--unknown-option"], 2), (["fail"], 7)],
)
def test_run_app_preserves_typer_exit_status(monkeypatch, args, expected_status) -> None:
    from st_sdk.runtime import run_app

    monkeypatch.delenv("ST_EXTENSION_CONTEXT", raising=False)
    app = typer.Typer()

    @app.callback()
    def root() -> None:
        pass

    @app.command()
    def fail() -> None:
        raise typer.Exit(7)

    with pytest.raises(SystemExit) as exc_info:
        run_app(app, "owner", args=args)

    assert exc_info.value.code == expected_status


def test_sdk_client_create_task_uses_selected_project(monkeypatch) -> None:
    from st_sdk.client import STClient

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "task-new"})

    client = STClient(
        base_url="http://summitflow.test/api",
        project_id="selected-project",
        transport=httpx.MockTransport(handler),
    )

    assert client.create_task({"title": "Promoted learning"}) == {"id": "task-new"}
    assert seen == {
        "url": "http://summitflow.test/api/projects/selected-project/tasks",
        "body": {"title": "Promoted learning"},
    }


def test_cli_compatibility_modules_preserve_public_identities() -> None:
    import importlib

    from st_sdk import context, http

    from cli import _client_base, output_context

    cli_usage = importlib.import_module("cli.lib.usage")
    sdk_usage = importlib.import_module("st_sdk.usage")

    assert _client_base.APIError is http.APIError
    assert _client_base.BaseHTTPClient is http.BaseHTTPClient
    assert output_context.OutputContext is context.OutputContext
    assert cli_usage.UsageSpec is sdk_usage.UsageSpec
    assert cli_usage.usage is sdk_usage.usage
