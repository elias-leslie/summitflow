"""`.index.yaml` generation."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from app.services.project_index.generator import (
    generate_index,
    get_network_info,
    get_project_urls,
    write_all_index_files,
    write_index_file,
)

_MODULE = "app.services.project_index.generator"


@pytest.fixture
def sources() -> Iterator[dict[str, Any]]:
    """Patch every live source with empty data; tests override what they assert on."""
    with (
        patch(f"{_MODULE}.get_environment", return_value={}) as environment,
        patch(f"{_MODULE}.get_services", return_value={}) as services,
        patch(f"{_MODULE}.get_project_config", return_value={}) as config,
        patch(f"{_MODULE}.get_network_info", return_value={}) as network,
        patch(f"{_MODULE}.discover_pages", return_value=[]) as pages,
    ):
        yield {"environment": environment, "services": services, "config": config, "network": network, "pages": pages}


def test_generate_index_with_no_data_is_minimal(sources: dict[str, Any]) -> None:
    parsed = yaml.safe_load(generate_index("test-project"))

    assert set(parsed) == {"project", "generated_at"}
    assert parsed["project"] == "test-project"


def test_generate_index_emits_exactly_the_consumed_keys(sources: dict[str, Any]) -> None:
    sources["environment"].return_value = {"python_version": ">=3.13"}
    sources["services"].return_value = {"backend_port": 8001, "frontend_port": 3001}
    sources["network"].return_value = {"host_ip": "10.0.0.1", "hostname": "test-host"}
    sources["pages"].return_value = [
        {"path": "/", "name": "home", "url": None, "port": 3001},
        {"path": "/git", "name": "git", "url": None, "port": 3001},
        {"path": "/projects/:id", "name": "projects/:id", "url": None, "port": 3001},
        {"path": "/x/:slug", "name": "detail", "url": None, "port": 3001},
    ]

    parsed = yaml.safe_load(generate_index("test-project"))

    assert list(parsed) == ["project", "generated_at", "environment", "services", "urls", "network", "pages"]
    assert parsed["services"] == {"backend_port": 8001, "frontend_port": 3001}
    assert parsed["urls"] == {"frontend": "http://localhost:3001", "api": "http://localhost:8001/api"}
    assert parsed["network"] == {"host_ip": "10.0.0.1", "hostname": "test-host"}
    # Labels that only repeat the path are dropped; informative ones stay.
    assert parsed["pages"] == ["/", "/git", "/projects/:id", "/x/:slug (detail)"]


def test_port_derived_url_takes_precedence_over_base_url() -> None:
    with patch(f"{_MODULE}.get_project_config", return_value={"base_url": "http://192.0.2.33:8000"}):
        urls = get_project_urls("portfolio-ai", {"backend_port": 8000, "frontend_port": 3000})

    assert urls == {"frontend": "http://localhost:3000", "api": "http://localhost:8000/api"}


def test_base_url_used_when_no_frontend_port() -> None:
    with patch(f"{_MODULE}.get_project_config", return_value={"base_url": "https://example.com/"}):
        urls = get_project_urls("test-project", {"backend_port": 8000})

    assert urls == {"frontend": "https://example.com", "api": "http://localhost:8000/api"}


def test_network_info_returns_host_ip_and_hostname() -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="192.0.2.44 172.17.0.1\n")
    with (
        patch(f"{_MODULE}.safe_subprocess.run", return_value=completed),
        patch(f"{_MODULE}.socket.gethostname", return_value="summitflow-prod"),
    ):
        assert get_network_info() == {"host_ip": "192.0.2.44", "hostname": "summitflow-prod"}


def test_network_info_is_empty_on_failure() -> None:
    with (
        patch(f"{_MODULE}.safe_subprocess.run", side_effect=OSError),
        patch(f"{_MODULE}.socket.gethostname", side_effect=OSError),
    ):
        assert get_network_info() == {}


def test_write_index_file_without_root_returns_none() -> None:
    with patch(f"{_MODULE}.get_project_root", return_value=None):
        assert write_index_file("test-project") is None


def test_write_index_file_writes_project_root(tmp_path: Path, sources: dict[str, Any]) -> None:
    with patch(f"{_MODULE}.get_project_root", return_value=str(tmp_path)):
        result = write_index_file("test-project")

    assert result == str(tmp_path / ".index.yaml")
    assert yaml.safe_load((tmp_path / ".index.yaml").read_text())["project"] == "test-project"


def test_timestamp_only_change_keeps_existing_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    index = tmp_path / ".index.yaml"
    original = "project: test\ngenerated_at: old\nservices:\n  backend_port: 1\n"
    index.write_text(original)
    monkeypatch.setattr(f"{_MODULE}.get_project_root", lambda _: str(tmp_path))
    monkeypatch.setattr(f"{_MODULE}.generate_index", lambda _: original.replace("old", "new"))
    write_index_file("test")
    assert index.read_text() == original

    monkeypatch.setattr(f"{_MODULE}.generate_index", lambda _: original.replace("old", "new").replace("port: 1", "port: 2"))
    write_index_file("test")
    assert "backend_port: 2" in index.read_text()
    assert "generated_at: new" in index.read_text()


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def test_generated_index_keeps_checkout_clean_including_existing_residue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q")
    index = tmp_path / ".index.yaml"
    content = "project: test\n"
    monkeypatch.setattr(f"{_MODULE}.get_project_root", lambda _: str(tmp_path))
    monkeypatch.setattr(f"{_MODULE}.generate_index", lambda _: content)
    exclude = tmp_path / ".git/info/exclude"
    exclude.write_text("# existing local rule\n/local-scratch")

    # Residue from a previous run: even a semantic no-op must exclude it.
    index.write_text(content)
    assert _git(tmp_path, "status", "--porcelain") == "?? .index.yaml"
    assert write_index_file("test") == str(index)
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert index.read_text() == content
    assert exclude.read_text().startswith("# existing local rule\n/local-scratch\n")

    # Future generation is also clean, and exclusion is idempotent and root-only.
    index.unlink()
    write_index_file("test")
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert exclude.read_text().splitlines().count("/.index.yaml") == 1
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".index.yaml").write_text("handwritten: true\n")
    assert _git(tmp_path, "status", "--porcelain", "--untracked-files=all") == "?? nested/.index.yaml"


def test_generated_index_preserves_tracked_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q")
    index = tmp_path / ".index.yaml"
    index.write_text("project: original\n")
    _git(tmp_path, "add", ".index.yaml")
    monkeypatch.setattr(f"{_MODULE}.get_project_root", lambda _: str(tmp_path))
    monkeypatch.setattr(f"{_MODULE}.generate_index", lambda _: "project: updated\n")

    write_index_file("test")

    assert index.read_text() == "project: updated\n"
    assert _git(tmp_path, "diff", "--name-only") == ".index.yaml"
    assert _git(tmp_path, "ls-files") == ".index.yaml"


class _Cursor:
    def __init__(self, rows: list[tuple[str]]) -> None:
        self.rows = rows
        self.sql = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, *_args: object) -> None:
        self.sql = sql

    def fetchall(self) -> list[tuple[str]]:
        return self.rows


def test_write_all_index_files_skips_testing_projects_and_isolates_failures() -> None:
    def write(project_id: str) -> str:
        if project_id == "broken":
            raise RuntimeError("boom")
        return f"/{project_id}/.index.yaml"

    cursor = _Cursor([("alpha",), ("broken",), ("fixture",)])
    with (
        patch("app.storage.connection.get_cursor", return_value=cursor),
        patch("app.storage.projects.testing_project_ids", return_value={"fixture"}),
        patch(f"{_MODULE}.write_index_file", side_effect=write),
    ):
        results = write_all_index_files()

    assert results == {"alpha": "/alpha/.index.yaml", "broken": None}
    # Retired projects often have no checkout left, so they are never scheduled.
    assert "project_retirement_decisions" in cursor.sql
