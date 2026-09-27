"""Agent discovery and standalone CLI examples must describe the same surface."""
from __future__ import annotations

import json
import shlex

from typer.testing import CliRunner

import monitor_standalone
from cli.commands import monitor
from cli.commands.tools import app as tools_app
from cli.lib.usage import collect_usage_specs, select_specs_for_density


def test_monitor_guidance_is_discoverable_without_expanding_core_context():
    specs = collect_usage_specs(monitor.app)
    surfaces = {spec.surface for spec in specs}
    assert {"st.monitor.status", "st.monitor.logs", "st.monitor.log-services",
            "st.monitor.processes", "st.monitor.capture", "st.monitor.series",
            "st.monitor.events", "st.monitor.mounts", "st.monitor.disk-space",
            "st.monitor.connections", "st.monitor.export"} <= surfaces
    core = select_specs_for_density(specs, density="core")
    assert not any(spec.surface.startswith("st.monitor.") for spec in core)
    assert "host and project troubleshooting" in next(spec.why for spec in core if spec.surface == "st.details")
    task = select_specs_for_density(specs, density="task", task_type="debugging")
    assert surfaces <= {spec.surface for spec in task}


def test_published_monitor_examples_parse_in_the_independent_launcher():
    parser = monitor_standalone._parser()
    for spec in collect_usage_specs(monitor.app):
        for example in spec.examples:
            argv = shlex.split(example)
            assert argv[:2] == ["st", "monitor"]
            parser.parse_args(argv[2:])


def test_exact_manifest_lookup_exposes_bounds_and_operational_requirements():
    result = CliRunner().invoke(tools_app, ["manifest", "--surface", "st.monitor.logs", "--format", "json"])
    assert result.exit_code == 0, result.output
    tools = json.loads(result.output)["tools"]
    assert [tool["surface"] for tool in tools] == ["st.monitor.logs"]
    text = " ".join(tools[0]["precautions"])
    assert "collector is required" in text
    assert "absolute since/until" in text
    assert "log-services" in text
