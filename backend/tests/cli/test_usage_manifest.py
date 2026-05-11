"""Tests for @usage decorator, registry walk, and `st tools manifest`."""

from __future__ import annotations

import json

import typer
from typer.testing import CliRunner

from cli.commands.tools import app as tools_app
from cli.lib.usage import (
    UsageSpec,
    collect_usage_specs,
    filter_specs,
    usage,
)

runner = CliRunner()


def test_usage_stamps_spec_on_callback() -> None:
    @usage(surface="st.fake.surface", cmd="st fake", task_types=("devops",))
    def _fn() -> None: ...

    spec = _fn.__st_usage__  # type: ignore[attr-defined]
    assert isinstance(spec, UsageSpec)
    assert spec.surface == "st.fake.surface"
    assert spec.cmd == "st fake"
    assert spec.task_types == ("devops",)


def test_usage_rejects_empty_surface_and_bad_tier() -> None:
    import pytest

    with pytest.raises(ValueError, match="surface"):
        usage(surface="")
    with pytest.raises(ValueError, match="tier"):
        usage(surface="st.x", tier="critical")


def test_collect_walks_subgroups() -> None:
    root = typer.Typer()
    sub = typer.Typer()
    root.add_typer(sub, name="sub")

    @sub.command()
    @usage(surface="st.sub.cmd", cmd="st sub cmd")
    def _cmd() -> None: ...

    specs = collect_usage_specs(root)
    assert [s.surface for s in specs] == ["st.sub.cmd"]


def test_collect_skips_undecorated_callbacks() -> None:
    root = typer.Typer()

    @root.command()
    def _plain() -> None: ...

    @root.command()
    @usage(surface="st.only.this")
    def _decorated() -> None: ...

    surfaces = [s.surface for s in collect_usage_specs(root)]
    assert surfaces == ["st.only.this"]


def test_filter_specs_by_task_type() -> None:
    specs = [
        UsageSpec(surface="st.a", task_types=("devops",)),
        UsageSpec(surface="st.b", task_types=("frontend",)),
        UsageSpec(surface="st.c"),  # empty == all
    ]
    out = filter_specs(specs, task_type="devops")
    assert [s.surface for s in out] == ["st.a", "st.c"]


def test_filter_specs_by_surface() -> None:
    specs = [UsageSpec(surface="st.a"), UsageSpec(surface="st.b")]
    out = filter_specs(specs, surface="st.b")
    assert [s.surface for s in out] == ["st.b"]


def test_manifest_command_emits_service_rebuild_yaml() -> None:
    result = runner.invoke(tools_app, ["manifest", "--surface", "st.service.rebuild", "--format", "yaml"])
    assert result.exit_code == 0, result.output
    assert "surface: st.service.rebuild" in result.output
    assert "tier: mandate" in result.output
    assert "--include-all-workers" in result.output


def test_manifest_command_emits_json_with_version() -> None:
    result = runner.invoke(tools_app, ["manifest", "--surface", "st.service.rebuild", "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["manifest_version"] == 1
    assert payload["tools"][0]["surface"] == "st.service.rebuild"


def test_manifest_command_filter_excludes_task_specific_surfaces() -> None:
    """A task filter retains universal (empty task_types) surfaces and any
    surface that explicitly declares the requested task type. Surfaces tagged
    for a different task are excluded.

    st.service.rebuild intentionally lists frontend/backend in its task_types
    so frontend/backend code changes route through the managed build+restart
    cycle instead of raw pnpm/npm/uv builds.
    """
    frontend = runner.invoke(tools_app, ["manifest", "--task", "frontend", "--format", "json"])
    devops = runner.invoke(tools_app, ["manifest", "--task", "devops", "--format", "json"])
    assert frontend.exit_code == 0
    assert devops.exit_code == 0
    frontend_surfaces = {t["surface"] for t in json.loads(frontend.output)["tools"]}
    devops_surfaces = {t["surface"] for t in json.loads(devops.output)["tools"]}
    assert "st.browser" in frontend_surfaces
    assert "st.browser" not in devops_surfaces
    assert "st.service.rebuild" in devops_surfaces
    assert "st.service.rebuild" in frontend_surfaces
    # st.sessions.ownership is exclusively devops — verifies task filtering
    # still excludes surfaces that don't list the requested task type.
    assert "st.sessions.ownership" in devops_surfaces
    assert "st.sessions.ownership" not in frontend_surfaces


def test_manifest_command_rejects_unknown_format() -> None:
    result = runner.invoke(tools_app, ["manifest", "--format", "xml"])
    assert result.exit_code == 1
    assert "Unknown --format" in result.output
