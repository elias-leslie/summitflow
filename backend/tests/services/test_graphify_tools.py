"""Graphify tool resolution tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import graphify_tools
from app.services.graphify_tools import GraphifyCommandResult


def test_graphify_bin_skips_broken_shebang_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "graphify"
    broken.write_text("#!/missing/python\nprint('nope')\n", encoding="utf-8")
    broken.chmod(0o755)
    fallback = tmp_path / "fallback-graphify"
    fallback.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fallback.chmod(0o755)

    monkeypatch.delenv("GRAPHIFY_BIN", raising=False)
    monkeypatch.setattr(graphify_tools.shutil, "which", lambda _: str(broken))
    monkeypatch.setattr(graphify_tools, "_DEFAULT_GRAPHIFY_BIN", fallback)

    assert graphify_tools.graphify_bin() == str(fallback)


def test_graphify_bin_reports_unrunnable_configured_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "graphify"
    broken.write_text("#!/missing/python\nprint('nope')\n", encoding="utf-8")
    broken.chmod(0o755)

    monkeypatch.setenv("GRAPHIFY_BIN", str(broken))

    with pytest.raises(FileNotFoundError, match="not runnable"):
        graphify_tools.graphify_bin()


def test_graphify_status_accepts_code_graph_without_detect_cache(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("def main():\n    return 1\n", encoding="utf-8")
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(
        '{"nodes":[{"id":"app","file_type":"code","source_file":"app.py"}],"links":[]}',
        encoding="utf-8",
    )

    status = graphify_tools.graphify_status("project", tmp_path)

    assert "detect_missing" not in status["diagnostics"]


def test_refresh_graph_prunes_deleted_code_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = tmp_path / "existing.py"
    existing.write_text("def keep():\n    return 1\n", encoding="utf-8")
    out = tmp_path / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text(
        (
            '{"nodes":['
            '{"id":"keep","file_type":"code","source_file":"existing.py"},'
            '{"id":"gone","file_type":"code","source_file":"missing.py"},'
            '{"id":"gone_note","file_type":"rationale","source_file":"missing.py"}'
            '],"links":[{"source":"keep","target":"gone"},{"source":"keep","target":"keep"}]}'
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(root: Path, args: list[str], *, timeout: int = 180) -> GraphifyCommandResult:
        calls.append(args)
        return GraphifyCommandResult(
            command=["graphify", *args],
            output="updated",
            elapsed_ms=1,
            output_chars=7,
            estimated_tokens=2,
        )

    monkeypatch.setattr(graphify_tools, "run_graphify", fake_run)

    result = graphify_tools.refresh_graph(tmp_path)
    data = graphify_tools._read_json(out / "graph.json")

    assert calls == [["update", str(tmp_path), "--force"]]
    assert [node["id"] for node in data["nodes"]] == ["keep"]
    assert data["links"] == [{"source": "keep", "target": "keep"}]
    assert "Pruned 2 stale code/rationale node(s)" in result.output
