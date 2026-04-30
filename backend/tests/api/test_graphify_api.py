"""Tests for Graphify project graph endpoints."""

from __future__ import annotations

import os
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.graphify_tools import GraphifyCommandResult
from app.storage.connection import get_connection


@pytest.fixture
def graphify_project(db_schema_initialized: None, tmp_path: Path) -> Generator[tuple[str, Path]]:
    project_id = "graphify-api-test"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
            SET name = EXCLUDED.name,
                base_url = EXCLUDED.base_url,
                root_path = EXCLUDED.root_path
            """,
            (project_id, "Graphify API Test", "http://localhost:3001", str(tmp_path)),
        )
        conn.commit()

    yield project_id, tmp_path

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


def _write_graphify_outputs(root: Path) -> None:
    out = root / "graphify-out"
    out.mkdir()
    code_source = root / "backend" / "app.py"
    code_source.parent.mkdir(parents=True)
    code_source.write_text("def run() -> None:\n    pass\n", encoding="utf-8")
    doc_source = root / "docs" / "note.md"
    doc_source.parent.mkdir(parents=True)
    doc_source.write_text("# Note\n", encoding="utf-8")
    (out / "graph.json").write_text(
        """
        {
          "nodes": [
            {"id": "a", "label": "A", "community": 1, "file_type": "code"},
            {"id": "b", "label": "B", "community": 1, "file_type": "rationale"},
            {"id": "c", "label": "C", "community": 2, "file_type": "document"}
          ],
          "links": [{"source": "a", "target": "c", "relation": "explains"}]
        }
        """,
        encoding="utf-8",
    )
    (out / "graph.html").write_text(
        "<!doctype html><script src='https://cdn.jsdelivr.net/npm/d3'></script><title>Graph</title>",
        encoding="utf-8",
    )
    (out / "GRAPH_REPORT.md").write_text("# Report\n", encoding="utf-8")
    (out / ".graphify_detect.json").write_text(
        f"""
        {{
          "files": {{
            "code": ["{code_source}"],
            "document": ["{doc_source}"]
          }}
        }}
        """,
        encoding="utf-8",
    )
    old_timestamp = time.time() - 60
    for artifact in (out / "graph.json", out / "graph.html", out / "GRAPH_REPORT.md"):
        os.utime(artifact, (old_timestamp, old_timestamp))
    os.utime(code_source, (old_timestamp, old_timestamp))
    os.utime(doc_source, None)


def test_graphify_status_and_static_outputs(
    client: TestClient,
    graphify_project: tuple[str, Path],
) -> None:
    project_id, root = graphify_project
    _write_graphify_outputs(root)

    status_response = client.get(f"/api/projects/{project_id}/graphify/status")
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["graph_exists"] is True
    assert status["html_available"] is True
    assert status["report_available"] is True
    assert status["node_count"] == 3
    assert status["edge_count"] == 1
    assert status["community_count"] == 2
    assert status["code_node_count"] == 1
    assert status["rationale_node_count"] == 1
    assert status["semantic_node_count"] == 1
    assert status["detected_source_counts"] == {"code": 1, "document": 1}
    assert status["semantic_source_count"] == 1
    assert status["semantic_coverage"] == "semantic"
    assert status["graph_stale"] is True
    assert status["changed_files_since_graph"] == 1
    assert status["changed_files_sample"] == ["docs/note.md"]
    assert status["graph_size_bytes"] > 0
    assert status["html_size_bytes"] > 0
    assert status["report_size_bytes"] > 0
    assert status["html_uses_cdn"] is True
    assert status["diagnostics"] == ["graph_stale", "html_uses_external_cdn"]
    assert status["html_url"] == f"/api/projects/{project_id}/graphify/html"

    html_response = client.get(f"/api/projects/{project_id}/graphify/html")
    assert html_response.status_code == 200
    assert "Graph" in html_response.text

    report_response = client.get(f"/api/projects/{project_id}/graphify/report")
    assert report_response.status_code == 200
    assert report_response.text == "# Report\n"


def test_graphify_update_runs_code_only_refresh(
    client: TestClient,
    graphify_project: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, root = graphify_project
    _write_graphify_outputs(root)
    calls: list[Path] = []

    def fake_refresh(refresh_root: Path) -> GraphifyCommandResult:
        calls.append(refresh_root)
        return GraphifyCommandResult(
            command=["graphify", "update", str(refresh_root)],
            output="updated",
            elapsed_ms=5,
            output_chars=7,
            estimated_tokens=2,
        )

    monkeypatch.setattr("app.api.graphify.refresh_graph", fake_refresh)

    response = client.post(f"/api/projects/{project_id}/graphify/update")
    assert response.status_code == 200
    assert response.json()["output"] == "updated"
    assert calls == [root.resolve()]


def test_graphify_command_endpoints_return_measured_output(
    client: TestClient,
    graphify_project: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id, root = graphify_project
    _write_graphify_outputs(root)
    calls: list[tuple[str, tuple[object, ...]]] = []

    def result(command: str, output: str) -> GraphifyCommandResult:
        return GraphifyCommandResult(
            command=["graphify", command],
            output=output,
            elapsed_ms=12,
            output_chars=len(output),
            estimated_tokens=2,
        )

    def fake_query(query_root: Path, question: str, *, budget: int, dfs: bool) -> GraphifyCommandResult:
        calls.append(("query", (query_root, question, budget, dfs)))
        return result("query", "answer")

    def fake_path(path_root: Path, source: str, target: str) -> GraphifyCommandResult:
        calls.append(("path", (path_root, source, target)))
        return result("path", "a -> b")

    def fake_explain(explain_root: Path, node: str) -> GraphifyCommandResult:
        calls.append(("explain", (explain_root, node)))
        return result("explain", "node detail")

    monkeypatch.setattr("app.api.graphify.query_graph", fake_query)
    monkeypatch.setattr("app.api.graphify.path_graph", fake_path)
    monkeypatch.setattr("app.api.graphify.explain_graph", fake_explain)

    query_response = client.post(
        f"/api/projects/{project_id}/graphify/query",
        json={"question": "central modules?", "budget": 900, "dfs": True},
    )
    path_response = client.post(
        f"/api/projects/{project_id}/graphify/path",
        json={"source": "A", "target": "B"},
    )
    explain_response = client.post(
        f"/api/projects/{project_id}/graphify/explain",
        json={"node": "A"},
    )

    assert query_response.status_code == 200
    assert query_response.json()["estimated_tokens"] == 2
    assert path_response.status_code == 200
    assert path_response.json()["output"] == "a -> b"
    assert explain_response.status_code == 200
    assert explain_response.json()["output_chars"] == len("node detail")
    assert calls == [
        ("query", (root.resolve(), "central modules?", 900, True)),
        ("path", (root.resolve(), "A", "B")),
        ("explain", (root.resolve(), "A")),
    ]
