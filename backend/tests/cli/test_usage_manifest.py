"""Tests for @usage decorator, registry walk, and `st tools manifest`."""

from __future__ import annotations

import json

import pytest
import typer
from typer.testing import CliRunner

from cli.commands.tools import app as tools_app
from cli.lib.usage import (
    VALID_MANIFEST_DENSITIES,
    UsageSpec,
    collect_usage_specs,
    discover_specs,
    filter_specs,
    render_inject,
    select_specs_for_density,
    usage,
)

runner = CliRunner()


@pytest.mark.parametrize("density", ["core", "adaptive"])
def test_desktop_startup_hint_is_compact_and_batch_details_are_on_demand(density):
    result = runner.invoke(tools_app, ["manifest", "--density", density, "--profile", "agent_startup", "--format", "json"])
    assert result.exit_code == 0, result.output
    specs = {row["surface"]: row for row in json.loads(result.output)["tools"]}
    assert "st.ui.inspect" in specs
    assert "run batches" in specs["st.ui.inspect"]["when"]
    assert "st.ui.run" not in specs
    detail = runner.invoke(tools_app, ["manifest", "--surface", "st.ui.run", "--format", "json"])
    assert detail.exit_code == 0, detail.output
    assert json.loads(detail.output)["tools"][0]["on_demand"] == "desktop UI"


@pytest.mark.parametrize("density", ["core", "adaptive"])
def test_memory_guidance_is_deferred_from_startup_even_with_history(density, tmp_path):
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({f"memory {command}": 100 for command in ("search", "save", "update")}))
    result = runner.invoke(tools_app, [
        "manifest", "--density", density, "--profile", "agent_startup",
        "--scores-file", str(scores), "--format", "json",
    ])
    assert result.exit_code == 0, result.output
    specs = {row["surface"]: row for row in json.loads(result.output)["tools"]}
    assert not {"st.memory.search", "st.memory.save", "st.memory.update"} & specs.keys()
    assert "st.details" in specs


def test_deferred_memory_guidance_is_discoverable_and_complete_in_full_density():
    surfaces = {"st.memory.search", "st.memory.save", "st.memory.update"}
    discovery = runner.invoke(tools_app, ["manifest", "--discover", "memory authoring", "--format", "json"])
    assert discovery.exit_code == 0, discovery.output
    discovered = {row["surface"]: row for row in json.loads(discovery.output)["tools"]}
    assert surfaces <= discovered.keys()
    assert all(discovered[surface]["on_demand"] == "memory authoring" for surface in surfaces)

    full = runner.invoke(tools_app, ["manifest", "--density", "full", "--profile", "agent_startup", "--format", "json"])
    assert full.exit_code == 0, full.output
    specs = {row["surface"]: row for row in json.loads(full.output)["tools"]}
    assert surfaces <= specs.keys()
    for surface in surfaces:
        exact = runner.invoke(tools_app, ["manifest", "--surface", surface, "--format", "json"])
        assert exact.exit_code == 0, exact.output
        assert specs[surface] == json.loads(exact.output)["tools"][0]


@pytest.mark.parametrize("query", ["github", "elevate"])
def test_github_admin_elevation_is_deferred_but_discoverable(query: str) -> None:
    discovery = runner.invoke(tools_app, ["manifest", "--discover", query, "--format", "json"])
    assert discovery.exit_code == 0, discovery.output
    rows = {row["surface"]: row for row in json.loads(discovery.output)["tools"]}
    assert "st.elevate" in rows
    startup = runner.invoke(tools_app, ["manifest", "--profile", "agent_startup", "--format", "json"])
    assert "st.elevate" not in {row["surface"] for row in json.loads(startup.output)["tools"]}


def test_inject_renders_one_line_per_command_with_every_precaution() -> None:
    specs = [
        UsageSpec(surface="st.a", cmd="st a", when="do a", precautions=("p1", "p2"), tier="mandate"),
        UsageSpec(surface="st.b", cmd="st b", tier="reference"),
    ]
    assert render_inject(specs) == "mandates:\n- st a — do a — careful: p1; p2\nreferences:\n- st b"


def test_compact_discovery_covers_ordinary_task_work_without_full_catalogue() -> None:
    result = runner.invoke(tools_app, ["manifest", "--format", "json"])
    assert result.exit_code == 0, result.output
    specs = {row["surface"]: row for row in json.loads(result.output)["tools"]}
    for surface in ("st.context", "st.claim", "st.check", "st.commit", "st.done"):
        exact = runner.invoke(tools_app, ["manifest", "--surface", surface, "--format", "json"])
        assert exact.exit_code == 0
        assert specs[surface] == json.loads(exact.output)["tools"][0]
    assert not {"st.vcs.publish", "st.design", "st.ui.gif", "st.vm.status"} & specs.keys()


@pytest.mark.parametrize("task", [None, "backend", "verification"])
def test_specialized_guidance_is_not_selected_by_unrelated_task_or_history(tmp_path, task) -> None:
    scores = tmp_path / "scores.json"
    scores.write_text(json.dumps({"design asset import": 100, "tools cost": 100, "ui gif": 100}))
    args = ["manifest", "--density", "adaptive", "--scores-file", str(scores), "--format", "json"]
    if task:
        args += ["--task", task]
    result = runner.invoke(tools_app, args)
    assert result.exit_code == 0, result.output
    specs = {row["surface"]: row for row in json.loads(result.output)["tools"]}
    assert {"st.claim", "st.context", "st.check", "st.db", "st.service.rebuild"} <= specs.keys()
    assert not {"st.design", "st.models", "st.tools.cost", "st.ui.gif", "st.vm.status", "st.agents.get", "st.autonomous.upkeep"} & specs.keys()


@pytest.mark.parametrize(("task", "surface"), [
    ("design", "st.design"), ("ui-design", "st.design"),
    ("agent-admin", "st.agents.get"), ("model-admin", "st.models"),
    ("tool-governance", "st.tools.cost"), ("vm-repair", "st.vm.status"),
    ("recording", "st.ui.gif"),
])
def test_explicit_specialized_work_gets_complete_canonical_guidance(task, surface) -> None:
    selected = runner.invoke(tools_app, ["manifest", "--task", task, "--density", "adaptive", "--format", "json"])
    full = runner.invoke(tools_app, ["manifest", "--surface", surface, "--format", "json"])
    assert selected.exit_code == full.exit_code == 0
    selected_spec = next(row for row in json.loads(selected.output)["tools"] if row["surface"] == surface)
    assert selected_spec == json.loads(full.output)["tools"][0]


@pytest.mark.parametrize("density", ["full", "task", "adaptive"])
@pytest.mark.parametrize("task", ["ui-design", "agent-admin", "model-admin", "tool-governance", "vm-repair"])
def test_task_delimiters_from_live_consumers_match_cli_names(density, task) -> None:
    def surfaces(value):
        result = runner.invoke(tools_app, ["manifest", "--task", value, "--density", density, "--format", "json"])
        assert result.exit_code == 0
        return json.loads(result.output)["tools"]

    assert surfaces(task.replace("-", "_")) == surfaces(task)


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


def test_select_specs_for_core_density_adds_drilldown_surface() -> None:
    specs = [
        UsageSpec(surface="st.create"),
        UsageSpec(surface="st.search"),
        UsageSpec(surface="st.browser", task_types=("frontend",)),
    ]

    out = select_specs_for_density(specs, density="core")

    assert [s.surface for s in out] == ["st.create", "st.search", "st.details"]


def test_select_specs_for_task_density_adds_matching_task_surfaces() -> None:
    specs = [
        UsageSpec(surface="st.search"),
        UsageSpec(surface="st.browser", task_types=("frontend",)),
        UsageSpec(surface="st.sessions.ownership", task_types=("devops",)),
    ]

    out = select_specs_for_density(specs, density="task", task_type="frontend")

    assert [s.surface for s in out] == ["st.search", "st.browser", "st.details"]


def test_select_specs_adaptive_floor_always_present() -> None:
    specs = [
        UsageSpec(surface="st.commit"),
        UsageSpec(surface="st.check"),
        UsageSpec(surface="st.backup.veeam"),  # non-floor, no score -> dropped
    ]

    out = select_specs_for_density(specs, density="adaptive", scores=None)

    surfaces = [s.surface for s in out]
    assert "st.commit" in surfaces
    assert "st.check" in surfaces
    assert "st.backup.veeam" not in surfaces
    assert "st.details" in surfaces


def test_select_specs_adaptive_includes_high_score_surface() -> None:
    specs = [
        UsageSpec(surface="st.commit"),  # floor
        UsageSpec(surface="st.browser"),  # non-floor, scored high
        UsageSpec(surface="st.backup.veeam"),  # non-floor, scored low
    ]
    # usage-key granularity: "browser eval" maps to surface st.browser via prefix.
    scores = {"browser eval": 90.0, "backup veeam": 5.0}

    out = select_specs_for_density(specs, density="adaptive", scores=scores)

    surfaces = [s.surface for s in out]
    assert "st.commit" in surfaces  # floor
    assert "st.browser" in surfaces  # score >= threshold
    assert "st.backup.veeam" not in surfaces  # score below threshold


def test_select_specs_adaptive_includes_task_surface() -> None:
    specs = [
        UsageSpec(surface="st.search"),  # floor
        UsageSpec(surface="st.browser", task_types=("frontend",)),
    ]

    out = select_specs_for_density(specs, density="adaptive", task_type="frontend", scores=None)

    assert "st.browser" in [s.surface for s in out]


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


def test_manifest_command_orders_root_task_surfaces_deterministically() -> None:
    result = runner.invoke(tools_app, ["manifest", "--density", "full", "--format", "json"])

    assert result.exit_code == 0, result.output
    surfaces = [tool["surface"] for tool in json.loads(result.output)["tools"]]
    assert surfaces.index("st.claim") < surfaces.index("st.done") < surfaces.index("st.abandon")


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


def test_manifest_command_core_density_is_compact_and_drillable() -> None:
    full = runner.invoke(tools_app, ["manifest", "--density", "full", "--format", "json"])
    core = runner.invoke(tools_app, ["manifest", "--format", "json"])

    assert full.exit_code == 0, full.output
    assert core.exit_code == 0, core.output
    full_surfaces = {t["surface"] for t in json.loads(full.output)["tools"]}
    payload = json.loads(core.output)
    core_surfaces = {t["surface"] for t in payload["tools"]}
    assert payload["density"] == "core"
    assert "st.details" in core_surfaces
    assert "st.search" in core_surfaces
    assert "st.create" in full_surfaces
    assert "st.create" in core_surfaces
    assert len(core_surfaces) < len(full_surfaces)


def test_manifest_default_is_compact_but_explicit_task_and_full_are_available() -> None:
    default = runner.invoke(tools_app, ["manifest", "--format", "json"])
    task = runner.invoke(tools_app, ["manifest", "--task", "frontend", "--format", "json"])
    full = runner.invoke(tools_app, ["manifest", "--density", "full", "--format", "json"])

    assert default.exit_code == task.exit_code == full.exit_code == 0
    assert json.loads(default.output)["density"] == "core"
    assert json.loads(task.output)["density"] == "task"
    assert json.loads(full.output)["density"] == "full"
    assert len(json.loads(default.output)["tools"]) < len(json.loads(full.output)["tools"])
    assert "st.browser" in {spec["surface"] for spec in json.loads(task.output)["tools"]}


def test_manifest_unknown_surface_suggests_nearest_and_compact_discovery() -> None:
    result = runner.invoke(tools_app, ["manifest", "--surface", "st.service.rebulid"])

    assert result.exit_code == 1
    assert "st.service.rebuild" in result.output
    assert "st tools manifest --discover <family-or-workflow>" in result.output
    assert "--density full" in result.output


def test_manifest_unique_short_surface_avoids_discovery_retry() -> None:
    result = runner.invoke(tools_app, ["manifest", "--surface", "browser", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert [row["surface"] for row in json.loads(result.output)["tools"]] == ["st.browser"]


def test_manifest_ambiguous_short_surface_lists_choices() -> None:
    result = runner.invoke(tools_app, ["manifest", "--surface", "status"])

    assert result.exit_code == 1
    assert "Ambiguous --surface 'status'" in result.output
    assert "st.tools.status" in result.output


def test_manifest_command_task_density_keeps_matching_surfaces() -> None:
    result = runner.invoke(
        tools_app,
        ["manifest", "--task", "frontend", "--density", "task", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    surfaces = {t["surface"] for t in json.loads(result.output)["tools"]}
    assert "st.browser" in surfaces
    assert "st.sessions.ownership" not in surfaces
    assert "st.details" in surfaces


def test_manifest_command_rejects_unknown_density() -> None:
    result = runner.invoke(tools_app, ["manifest", "--density", "tiny"])

    assert result.exit_code == 1
    assert "Unknown --density" in result.output
    assert "|".join(VALID_MANIFEST_DENSITIES) in result.output


def test_manifest_command_rejects_unknown_format() -> None:
    result = runner.invoke(tools_app, ["manifest", "--format", "xml"])
    assert result.exit_code == 1
    assert "Unknown --format" in result.output


@pytest.mark.parametrize("query", ["service", "st.service", "sessions", "st.sessions", "backup", "st.backup"])
def test_manifest_discovers_registered_family_without_full_guidance(query) -> None:
    from cli.main import app as root_app

    family = query if query.startswith("st.") else f"st.{query}"
    expected = [spec for spec in collect_usage_specs(root_app) if spec.surface == family or spec.surface.startswith(family + ".")]
    result = runner.invoke(tools_app, ["manifest", "--discover", query, "--format", "json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload.keys() == {"manifest_version", "discovery_query", "tools"}
    assert payload["manifest_version"] == 1
    assert payload["discovery_query"] == query
    assert expected
    assert payload["tools"] == [
        {key: value for key, value in spec.to_dict().items() if key in {"surface", "cmd", "on_demand"}}
        for spec in expected
    ]


@pytest.mark.parametrize("query", ["completion", "agent-context", "agent_context", "agent context", "  AGENT   CONTEXT  ", "tool-telemetry"])
def test_manifest_discovers_normalized_registered_workflow(query) -> None:
    from cli.main import app as root_app

    label = " ".join(query.casefold().replace("-", " ").replace("_", " ").split())
    expected = [spec.surface for spec in collect_usage_specs(root_app) if spec.on_demand == label]
    result = runner.invoke(tools_app, ["manifest", "--discover", query, "--format", "json"])
    assert result.exit_code == 0, result.output
    assert expected
    assert [row["surface"] for row in json.loads(result.output)["tools"]] == expected


@pytest.fixture
def discovery_registry(monkeypatch):
    from cli.commands import tools

    specs = [
        UsageSpec(surface="st.family.universal", cmd="st family universal", on_demand="family"),
        UsageSpec(surface="st.family.task", task_types=("ui-design",)),
        UsageSpec(surface="st.family.agent", agent_slugs=("owner",)),
        UsageSpec(surface="st.family.profile", consumer_profiles=("agent_runtime",)),
        UsageSpec(surface="st.family.all", task_types=("ui-design",), agent_slugs=("owner",), consumer_profiles=("agent_runtime",)),
        UsageSpec(surface="st.outside.label", on_demand="family"),
        UsageSpec(surface="st.private", on_demand="restricted", task_types=("devops",), agent_slugs=("owner",), consumer_profiles=("agent_runtime",)),
    ]
    monkeypatch.setattr(tools, "collect_usage_specs", lambda app: specs)
    return specs


@pytest.mark.parametrize(("args", "excluded"), [
    (["--task", "backend"], {"st.family.task", "st.family.all"}),
    (["--agent", "other"], {"st.family.agent", "st.family.all"}),
    (["--profile", "agent_startup"], {"st.family.profile", "st.family.all"}),
    (["--task", "backend", "--agent", "other", "--profile", "agent_startup"], {"st.family.task", "st.family.agent", "st.family.profile", "st.family.all"}),
])
def test_manifest_discovery_preserves_applicability_filters(discovery_registry, args, excluded) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", "family", "--format", "json", *args])
    assert result.exit_code == 0, result.output
    assert [row["surface"] for row in json.loads(result.output)["tools"]] == [
        spec.surface for spec in discovery_registry if spec.surface != "st.private" and spec.surface not in excluded
    ]


def test_discovery_task_delimiters_and_family_workflow_overlap(discovery_registry) -> None:
    outputs = []
    for task in ("ui-design", "ui_design"):
        result = runner.invoke(tools_app, ["manifest", "--discover", "family", "--task", task, "--agent", "owner", "--profile", "agent_runtime", "--format", "json"])
        assert result.exit_code == 0, result.output
        outputs.append(json.loads(result.output))
    assert outputs[0] == outputs[1]
    assert [row["surface"] for row in outputs[0]["tools"]] == [spec.surface for spec in discovery_registry if spec.surface != "st.private"]
    assert discover_specs([*discovery_registry, discovery_registry[0]], "family") == discovery_registry[:-1]


@pytest.mark.parametrize("args", [["--task", "backend"], ["--agent", "other"], ["--profile", "agent_startup"]])
def test_discovery_distinguishes_filtered_from_unknown_without_excluded_rows(discovery_registry, args) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", "restricted", *args])
    assert result.exit_code == 1
    assert "Filtered --discover topic" in result.output
    assert "st.private" not in result.output


@pytest.mark.parametrize("query", ["unknown-workflow", "families", "st.familyish", "agent contexts"])
def test_discovery_rejects_unknown_topics_without_fuzzy_aliases(discovery_registry, query) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", query])
    assert result.exit_code == 1
    assert "Unknown --discover topic" in result.output


@pytest.mark.parametrize("args", [["--discover", "   "], ["--discover", "service", "--surface", "st.service.rebuild"]])
def test_discovery_rejects_invalid_selector_usage(args) -> None:
    result = runner.invoke(tools_app, ["manifest", *args])
    assert result.exit_code == 2


def test_discovery_density_is_not_sliced_and_does_not_load_scores(monkeypatch, discovery_registry) -> None:
    from cli.commands import tools

    def forbidden_scores(path):
        raise AssertionError("explicit discovery must not read scores")

    monkeypatch.setattr(tools, "_load_scores_file", forbidden_scores)
    outputs = []
    for density in VALID_MANIFEST_DENSITIES:
        result = runner.invoke(tools_app, ["manifest", "--discover", "family", "--density", density, "--scores-file", "-", "--format", "json"])
        assert result.exit_code == 0, result.output
        outputs.append(json.loads(result.output))
    assert all(payload == outputs[0] for payload in outputs)


@pytest.mark.parametrize(("args", "message"), [(["--density", "tiny"], "Unknown --density"), (["--format", "xml"], "Unknown --format")])
def test_discovery_preserves_density_and_format_errors(args, message) -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", "service", *args])
    assert result.exit_code == 1
    assert message in result.output


@pytest.mark.parametrize("fmt", ["inject", "yaml", "markdown"])
def test_discovery_formats_render_same_compact_rows(discovery_registry, fmt) -> None:
    import yaml

    result = runner.invoke(tools_app, ["manifest", "--discover", "family", "--format", fmt])
    assert result.exit_code == 0, result.output
    expected = [spec.surface for spec in discovery_registry[:-1]]
    if fmt == "markdown":
        assert "Discovery: family" in result.output
        assert "**on_demand**: family" in result.output
        assert [line.removeprefix("### `").removesuffix("`") for line in result.output.splitlines() if line.startswith("### `")] == expected
    else:
        payload = yaml.safe_load(result.output)
        assert payload["discovery_query"] == "family"
        assert [row["surface"] for row in payload["tools"]] == expected
        assert all(row.keys() <= {"surface", "cmd", "on_demand"} for row in payload["tools"])


def test_discovery_exact_registered_id_returns_its_own_row() -> None:
    result = runner.invoke(tools_app, ["manifest", "--discover", "st.sessions.send", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert [row["surface"] for row in json.loads(result.output)["tools"]] == ["st.sessions.send"]


def test_density_tiers_come_from_the_tool_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from cli import tool_registry
    from cli.lib import usage as usage_lib

    specs = [UsageSpec(surface="st.floor"), UsageSpec(surface="st.core"), UsageSpec(surface="st.busy"),
             UsageSpec(surface="st.other")]
    registry = {"usage_tiers": {"floor": ["st.floor"], "core": ["st.core"], "adaptive_score_threshold": 40}}
    monkeypatch.setattr(tool_registry, "load_tool_registry", lambda: registry)

    core = [spec.surface for spec in usage_lib.select_specs_for_density(specs, density="core")
            if spec.surface != "st.details"]
    adaptive = [spec.surface for spec in usage_lib.select_specs_for_density(
        specs, density="adaptive", scores={"busy": 50, "other": 30}) if spec.surface != "st.details"]
    assert core == ["st.floor", "st.core"]
    assert adaptive == ["st.floor", "st.busy"]


def test_committed_registry_keeps_the_implementation_floor() -> None:
    from cli.lib.usage import _usage_tiers

    floor, core, threshold = _usage_tiers()
    assert {"st.search", "st.context", "st.check", "st.commit", "st.claim", "st.done"} <= floor
    assert "st.check" in core and threshold > 0


def test_preview_is_always_injected_and_has_compact_passive_help(monkeypatch) -> None:
    # Exercise bundled metadata even when this host still runs the prior accepted release.
    from cli import extensions
    monkeypatch.setattr(extensions, "_owner_manifest", lambda binding: None)
    from cli.main import app
    for density in ("core", "adaptive"):
        result = runner.invoke(app, ["tools", "manifest", "--density", density, "--format", "inject", "--profile", "agent_startup"])
        assert result.exit_code == 0, result.output
        line = next(line for line in result.output.splitlines() if "st browser preview" in line)
        assert "<file-or-url> [--session NAME]" in line
        assert "leave it open" in line and "printed session" in line
        assert len(line) < 350
    help_result = runner.invoke(app, ["browser", "preview", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "st browser preview <file-or-url> [--session NAME]" in help_result.output
    assert len(help_result.output) < 700
