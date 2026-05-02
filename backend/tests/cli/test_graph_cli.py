"""Tests for Graphify CLI helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from app.services.graphify_tools import GraphifyCommandResult
from cli.commands import graph

runner = CliRunner()


def _status(project_id: str = "summitflow", diagnostics: list[str] | None = None) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "root_path": "/repo",
        "graph_exists": True,
        "html_available": True,
        "report_available": True,
        "node_count": 10,
        "edge_count": 20,
        "community_count": 3,
        "graph_updated_at": None,
        "html_updated_at": None,
        "report_updated_at": None,
        "html_url": "/api/projects/summitflow/graphify/html",
        "report_url": "/api/projects/summitflow/graphify/report",
        "code_node_count": 8,
        "rationale_node_count": 1,
        "semantic_node_count": 1,
        "file_type_counts": {"code": 8, "document": 1, "rationale": 1},
        "detected_source_counts": {"code": 12, "document": 1},
        "semantic_source_count": 1,
        "semantic_coverage": "semantic",
        "graph_stale": False,
        "changed_files_since_graph": 0,
        "changed_files_sample": [],
        "graph_size_bytes": 1000,
        "html_size_bytes": 2000,
        "report_size_bytes": 300,
        "html_uses_cdn": False,
        "diagnostics": diagnostics or [],
        "unreadable_error": None,
    }


def _result(command: str, output: str = "graph output") -> GraphifyCommandResult:
    return GraphifyCommandResult(
        command=["graphify", command],
        output=output,
        elapsed_ms=14,
        output_chars=len(output),
        estimated_tokens=3,
    )


def _json_line(output: str) -> dict[str, Any]:
    return json.loads(next(line for line in output.splitlines() if line.startswith("{")))


@pytest.fixture
def graph_cli_project(monkeypatch: pytest.MonkeyPatch) -> Path:
    root = Path("/repo")

    def fake_projects_api(method: str, path: str = "") -> object:
        assert method == "GET"
        if path == "/summitflow":
            return {"id": "summitflow", "root_path": str(root)}
        return [{"id": "summitflow", "root_path": str(root)}]

    monkeypatch.setattr(graph, "projects_api", fake_projects_api)
    return root


def test_status_reports_graphify_diagnostics(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graph, "graphify_status", lambda project_id, root: _status(project_id))

    result = runner.invoke(graph.app, ["status", "--project", "summitflow"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["project_id"] == "summitflow"
    assert payload["semantic_coverage"] == "semantic"
    assert payload["node_count"] == 10


def test_doctor_exits_nonzero_when_graph_has_agent_issues(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        graph,
        "graphify_status",
        lambda project_id, root: _status(project_id, ["graph_stale", "html_uses_external_cdn"]),
    )

    result = runner.invoke(graph.app, ["doctor", "--no-refresh"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["status"] == "ISSUES"
    assert payload["issue_count"] == 1
    assert payload["warning_count"] == 1
    assert payload["issues"][0]["diagnostics"] == ["graph_stale"]
    assert payload["warnings"][0]["diagnostics"] == ["html_uses_external_cdn"]


def test_doctor_all_uses_project_list_payload_without_per_project_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    calls: list[tuple[str, str]] = []

    def fake_projects_api(method: str, path: str = "") -> object:
        calls.append((method, path))
        assert method == "GET"
        if path:
            raise AssertionError("doctor should not refetch each project payload")
        return [{"id": "summitflow", "root_path": str(root)}]

    monkeypatch.setattr(graph, "projects_api", fake_projects_api)
    monkeypatch.setattr(graph, "graphify_status", lambda project_id, root: _status(project_id))

    result = runner.invoke(graph.app, ["doctor", "--no-refresh"])

    assert result.exit_code == 0
    assert json.loads(result.output)["projects"] == 1
    assert calls == [("GET", "")]


def test_status_auto_refreshes_stale_code_graph(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []

    def fake_status(project_id: str, root: Path) -> dict[str, Any]:
        if calls:
            return _status(project_id)
        return _status(project_id, ["graph_stale"])

    def fake_refresh(root: Path) -> GraphifyCommandResult:
        calls.append(root)
        return _result("update")

    monkeypatch.setattr(graph, "graphify_status", fake_status)
    monkeypatch.setattr(graph, "refresh_graph", fake_refresh)

    result = runner.invoke(graph.app, ["status", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "refreshed Graphify code graph before status" in result.output
    assert _json_line(result.output)["diagnostics"] == []
    assert calls == [graph_cli_project]


def test_query_auto_refresh_failure_uses_existing_graph(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(graph, "graphify_status", lambda project_id, root: _status(project_id, ["graph_stale"]))

    def fake_refresh(root: Path) -> GraphifyCommandResult:
        calls.append("refresh")
        raise RuntimeError("refresh failed")

    def fake_query(root: Path, question: str, *, budget: int, dfs: bool) -> GraphifyCommandResult:
        calls.append("query")
        return _result("query", "stale answer")

    monkeypatch.setattr(graph, "refresh_graph", fake_refresh)
    monkeypatch.setattr(graph, "query_graph", fake_query)

    result = runner.invoke(graph.app, ["query", "central modules?", "--project", "summitflow"])

    assert result.exit_code == 0
    assert "auto-refresh failed before query; using existing graph" in result.output
    assert _json_line(result.output)["output"] == "stale answer"
    assert calls == ["refresh", "query"]


def test_query_path_and_explain_output_measured_payloads(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    def fake_query(root: Path, question: str, *, budget: int, dfs: bool) -> GraphifyCommandResult:
        calls.append(("query", (root, question, budget, dfs)))
        return _result("query", "query answer")

    def fake_path(root: Path, source: str, target: str) -> GraphifyCommandResult:
        calls.append(("path", (root, source, target)))
        return _result("path", "A -> B")

    def fake_explain(root: Path, node: str) -> GraphifyCommandResult:
        calls.append(("explain", (root, node)))
        return _result("explain", "A detail")

    monkeypatch.setattr(graph, "query_graph", fake_query)
    monkeypatch.setattr(graph, "path_graph", fake_path)
    monkeypatch.setattr(graph, "explain_graph", fake_explain)
    monkeypatch.setattr(graph, "graphify_status", lambda project_id, root: _status(project_id))

    query_result = runner.invoke(
        graph.app,
        ["query", "central modules?", "--project", "summitflow", "--budget", "900", "--dfs"],
    )
    path_result = runner.invoke(graph.app, ["path", "A", "B", "--project", "summitflow"])
    explain_result = runner.invoke(graph.app, ["explain", "A", "--project", "summitflow"])

    assert query_result.exit_code == 0
    assert json.loads(query_result.output)["estimated_tokens"] == 3
    assert path_result.exit_code == 0
    assert json.loads(path_result.output)["output"] == "A -> B"
    assert explain_result.exit_code == 0
    assert json.loads(explain_result.output)["output_chars"] == len("A detail")
    assert calls == [
        ("query", (graph_cli_project, "central modules?", 900, True)),
        ("path", (graph_cli_project, "A", "B")),
        ("explain", (graph_cli_project, "A")),
    ]


def test_context_emits_prompt_ready_graph_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "GRAPH_REPORT.md").write_text(
        "# Graph Report - test\n\n## Summary\n- 10 nodes\n\n## Community Hubs\n- Hub A\n",
        encoding="utf-8",
    )

    def fake_projects_api(method: str, path: str = "") -> object:
        assert method == "GET"
        if path == "/summitflow":
            return {"id": "summitflow", "root_path": str(tmp_path)}
        return [{"id": "summitflow", "root_path": str(tmp_path)}]

    monkeypatch.setattr(graph, "projects_api", fake_projects_api)
    monkeypatch.setattr(graph, "graphify_status", lambda project_id, root: _status(project_id))

    result = runner.invoke(graph.app, ["context", "--project", "summitflow", "--budget", "600"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["project_id"] == "summitflow"
    assert "Use st graph query/path/explain" in payload["prompt_context"]
    assert "## Community Hubs" in payload["prompt_context"]
    assert payload["metadata"]["semantic_coverage"] == "semantic"


def test_semantic_refresh_no_execute_writes_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_projects_api(method: str, path: str = "") -> object:
        assert method == "GET"
        if path == "/summitflow":
            return {"id": "summitflow", "root_path": str(tmp_path)}
        return [{"id": "summitflow", "root_path": str(tmp_path)}]

    monkeypatch.setattr(graph, "projects_api", fake_projects_api)
    monkeypatch.setattr(
        graph,
        "graphify_status",
        lambda project_id, root: _status(project_id, ["semantic_sources_not_extracted"]),
    )

    result = runner.invoke(graph.app, ["semantic-refresh", "--project", "summitflow", "--no-execute"])

    assert result.exit_code == 0
    assert "GRAPH_SEMANTIC_REFRESH:READY" in result.output
    assert "--agent graphify-semantic-extractor" in result.output
    prompt = tmp_path / ".dev-tools" / "graphify-semantic-refresh-prompt-details.txt"
    assert prompt.exists()
    assert "Refresh Graphify semantic coverage" in prompt.read_text(encoding="utf-8")


def test_profile_compares_search_graph_and_agent_tool_shapes(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measured_commands: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return {
            "st": "/bin/st",
            "codex": "/bin/codex",
            "gitnexus": "/bin/gitnexus",
            "fallow": "/bin/fallow",
            "fallow-mcp": "/bin/fallow-mcp",
            "npm": "/bin/npm",
            "npx": "/bin/npx",
        }.get(name)

    def fake_run_measured(command: list[str], *, cwd: Path, timeout: int = 180) -> dict[str, Any]:
        measured_commands.append(command)
        return {
            "command": command,
            "exit_code": 0,
            "elapsed_ms": timeout,
            "output_chars": 40,
            "estimated_tokens": 10,
            "output_preview": "ok",
        }

    monkeypatch.setattr(graph.shutil, "which", fake_which)
    monkeypatch.setattr(graph, "_run_measured", fake_run_measured)
    monkeypatch.setattr(graph, "query_graph", lambda root, question, budget: _result("query"))
    monkeypatch.setattr(graph, "graphify_status", lambda project_id, root: _status(project_id))

    result = runner.invoke(
        graph.app,
        [
            "profile",
            "--project",
            "summitflow",
            "--codex",
            "--agent-hub",
            "--gitnexus",
            "--fallow",
            "--budget",
            "900",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["runs"][0]["command"][:4] == ["/bin/st", "-P", "summitflow", "search"]
    assert payload["runs"][1]["command"] == ["graphify", "query"]
    assert payload["tool_probes"][0]["command"] == ["/bin/codex", "--version"]
    assert payload["tool_probes"][1]["command"] == ["/bin/codex", "exec", "--help"]
    assert payload["tool_probes"][2]["command"][:6] == [
        "/bin/st",
        "-P",
        "agent-hub",
        "agents",
        "preview",
        "explorer",
    ]
    assert payload["tool_probes"][3]["tool"] == "gitnexus"
    assert payload["tool_probes"][3]["worth"] == "optional"
    assert payload["tool_probes"][3]["available"] is True
    assert payload["tool_probes"][3]["npx_available"] is True
    assert payload["tool_probes"][3]["metadata"]["command"][:3] == ["/bin/npm", "view", "gitnexus"]
    assert payload["tool_probes"][3]["startup"]["command"] == ["/bin/gitnexus", "--version"]
    assert payload["tool_probes"][3]["local_status"]["command"] == ["/bin/gitnexus", "status"]
    assert payload["tool_probes"][3]["context_probe"]["command"] == [
        "/bin/gitnexus",
        "context",
        "graphify_status",
    ]
    assert payload["tool_probes"][3]["impact_probe"]["command"] == [
        "/bin/gitnexus",
        "impact",
        "graphify_status",
        "--depth",
        "2",
    ]
    assert payload["tool_probes"][3]["manual_commands"]["codex_mcp"][:5] == [
        "codex",
        "mcp",
        "add",
        "gitnexus",
        "--",
    ]
    assert payload["tool_probes"][4]["tool"] == "fallow"
    assert payload["tool_probes"][4]["worth"] == "recommended_optional"
    assert payload["tool_probes"][4]["available"] is True
    assert payload["tool_probes"][4]["mcp_available"] is True
    assert payload["tool_probes"][4]["metadata"]["command"][:3] == ["/bin/npm", "view", "fallow"]
    assert payload["tool_probes"][4]["startup"]["command"] == ["/bin/fallow", "--version"]
    assert payload["tool_probes"][4]["plugins_probe"]["command"] == [
        "/bin/fallow",
        "list",
        "--format",
        "json",
        "--plugins",
    ]
    assert payload["tool_probes"][4]["audit_probe"]["command"] == [
        "/bin/fallow",
        "audit",
        "--format",
        "json",
        "--quiet",
    ]
    assert payload["tool_probes"][4]["health_score_probe"]["command"] == [
        "/bin/fallow",
        "health",
        "--format",
        "json",
        "--quiet",
        "--score",
    ]
    assert payload["tool_probes"][4]["changed_dead_code_probe"]["command"] == [
        "/bin/fallow",
        "dead-code",
        "--changed-since",
        "main",
        "--format",
        "json",
        "--quiet",
        "--summary",
    ]
    assert measured_commands[0][:4] == ["/bin/st", "-P", "summitflow", "search"]


def test_fallow_command_emits_compact_details_pointer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_projects_api(method: str, path: str = "") -> object:
        assert method == "GET"
        if path == "/summitflow":
            return {"id": "summitflow", "root_path": str(tmp_path)}
        return [{"id": "summitflow", "root_path": str(tmp_path)}]

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        text: bool,
        capture_output: bool,
        timeout: int,
        check: bool,
    ) -> graph.subprocess.CompletedProcess[str]:
        assert command == ["/bin/fallow", "audit", "--format", "json", "--quiet"]
        assert cwd == tmp_path
        assert text is True
        assert capture_output is True
        assert timeout == 120
        assert check is False
        return graph.subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                '{"verdict":"fail","changed_files_count":2,'
                '"summary":{"dead_code_issues":1,"complexity_findings":0,'
                '"duplication_clone_groups":0},'
                '"attribution":{"dead_code_introduced":1}}'
            ),
            stderr="full review details",
        )

    monkeypatch.setattr(graph, "projects_api", fake_projects_api)
    monkeypatch.setattr(graph.shutil, "which", lambda name: "/bin/fallow" if name == "fallow" else None)
    monkeypatch.setattr(graph.subprocess, "run", fake_run)

    result = runner.invoke(graph.app, ["fallow", "audit", "--project", "summitflow"])

    assert result.exit_code == 1
    assert result.output.startswith("FALLOW:audit:FAIL:1|")
    assert "details:.dev-tools/fallow-audit-details.txt" in result.output
    assert "hint:verdict=fail changed=2 dead=1 complexity=0 dupes=0 introduced=1" in result.output
    assert "full review details" not in result.output
    assert (tmp_path / ".dev-tools" / "fallow-audit-details.txt").read_text() == (
        '{"verdict":"fail","changed_files_count":2,'
        '"summary":{"dead_code_issues":1,"complexity_findings":0,'
        '"duplication_clone_groups":0},'
        '"attribution":{"dead_code_introduced":1}}\nfull review details'
    )
