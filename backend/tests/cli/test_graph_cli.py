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

    result = runner.invoke(graph.app, ["doctor"])

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["status"] == "ISSUES"
    assert payload["issue_count"] == 2
    assert payload["issues"][0]["diagnostics"] == ["graph_stale", "html_uses_external_cdn"]


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


def test_profile_compares_search_graph_and_agent_tool_shapes(
    graph_cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    measured_commands: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        return {"st": "/bin/st", "codex": "/bin/codex"}.get(name)

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

    result = runner.invoke(
        graph.app,
        ["profile", "--project", "summitflow", "--codex", "--agent-hub", "--budget", "900"],
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
    assert measured_commands[0][:4] == ["/bin/st", "-P", "summitflow", "search"]
