"""Agent discovery and standalone CLI examples must describe the same surface."""
from __future__ import annotations

import json
import shlex

import pytest
from typer.testing import CliRunner

import monitor_standalone
from cli.commands import monitor
from cli.commands.tools import app as tools_app
from cli.lib.usage import collect_usage_specs, select_specs_for_density
from monitor_extended import disk


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
    assert "container and package logs do not support priority or cursor" in text


@pytest.mark.parametrize("entrypoint", ["standalone", "typer"])
def test_disk_cli_is_local_and_preserves_partial_coverage(entrypoint, tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("local disk attribution attempted collector/store/backend access")

    for module in (monitor, monitor_standalone):
        monkeypatch.setattr(module, "observe_request", forbidden)
        monkeypatch.setattr(module, "MonitorReader", forbidden)
        monkeypatch.setattr(module, "monitor_state_dir", forbidden)
    scan = tmp_path / "scan"
    scan.mkdir()
    (scan / "visible").write_bytes(b"12345")
    (scan / "alias").symlink_to(tmp_path, target_is_directory=True)
    (scan / "locked").mkdir()
    (scan / "nested").mkdir()
    (scan / "nested/child").write_bytes(b"123")
    original_open = disk.os.open

    def deny_child(path, *args, **kwargs):
        if path == "locked":
            raise PermissionError("fixture permission denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(disk.os, "open", deny_child)

    def invoke(*args):
        if entrypoint == "standalone":
            code = monitor_standalone.main(["disk-space", *map(str, args)])
            output = capsys.readouterr().out
        else:
            result = CliRunner().invoke(monitor.app, ["disk-space", *map(str, args)])
            code, output = result.exit_code, result.stdout
        assert len(output.encode()) <= 4097
        return code, json.loads(output)

    code, result = invoke(scan)
    assert code == 0
    coverage = result["coverage"]
    assert coverage["measure"] == "regular_file_apparent_bytes"
    assert coverage["bytes_observed"] == 8
    assert coverage["entries_permission_denied"] == 1
    assert coverage["entries_hidden_or_skipped"] == 1
    assert coverage["complete"] is False
    _, capped = invoke(scan, "--max-entries", "1")
    assert capped["coverage"]["stop_reason"] == "entry_cap"
    _, depth = invoke(scan / "nested", "--max-depth", "0")
    assert depth["coverage"]["bytes_observed"] == 3
    _, depth = invoke(scan, "--max-depth", "0")
    assert depth["coverage"]["stop_reason"] == "depth_cap"
    code, error = invoke(scan / "alias")
    assert code == 1 and error["errors"][0]["code"] == "query_error"


@pytest.mark.parametrize("args", [
    ["--max-entries", "10001"], ["--max-depth", "13"],
    ["--timeout-seconds", "6"], ["--limit", "101"], ["--max-bytes", "511"],
])
def test_disk_cli_rejects_out_of_bounds_arguments(args):
    with pytest.raises(SystemExit) as error:
        monitor_standalone._parser().parse_args(["disk-space", "/var", *args])
    assert error.value.code == 2
    assert CliRunner().invoke(monitor.app, ["disk-space", "/var", *args]).exit_code == 2
