"""Tests for lease-scoped changed-file detection in st check.

Regression coverage for shared-checkout parallel refactors: a `--changed-only`
run scoped by ST_CHECK_LEASE_SCOPE must consider only the current agent's leased
files, never another in-flight agent's uncommitted churn.
"""

from __future__ import annotations

import types

import pytest

from cli.commands import check_changed
from cli.lib import leases


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path / "leases")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "")
    return tmp_path


def _repo(tmp_path):
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    (root / "mine.py").write_text("x = 1\n")
    (root / "theirs.py").write_text("y = 2\n")
    return root


def _point_config_at(monkeypatch, pid, root):
    monkeypatch.setattr(
        check_changed,
        "get_config_optional",
        lambda: types.SimpleNamespace(project_id=pid, project_root=str(root)),
        raising=False,
    )


def test_scope_keeps_only_leased_files(isolated_store, monkeypatch):
    root = _repo(isolated_store)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("ex", [str(root / "mine.py")], project_root=str(root))
    _point_config_at(monkeypatch, "ex", root)

    scoped = check_changed._scope_to_leases(root, ["mine.py", "theirs.py"])
    assert scoped == ["mine.py"]


def test_scope_no_leases_returns_all(isolated_store, monkeypatch):
    """No declared scope → unchanged behaviour (full changed set)."""
    root = _repo(isolated_store)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    _point_config_at(monkeypatch, "ex", root)

    scoped = check_changed._scope_to_leases(root, ["mine.py", "theirs.py"])
    assert scoped == ["mine.py", "theirs.py"]


def test_scope_ignores_other_agents_leases(isolated_store, monkeypatch):
    """A lease held by another agent does not scope my run (I hold none)."""
    root = _repo(isolated_store)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    leases.acquire("ex", [str(root / "theirs.py")], project_root=str(root))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    _point_config_at(monkeypatch, "ex", root)

    scoped = check_changed._scope_to_leases(root, ["mine.py", "theirs.py"])
    assert scoped == ["mine.py", "theirs.py"]


def test_changed_files_applies_scope_only_when_enabled(isolated_store, monkeypatch):
    """ST_CHECK_LEASE_SCOPE gates the scoping; otherwise the override path is verbatim."""
    root = _repo(isolated_store)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("ex", [str(root / "mine.py")], project_root=str(root))
    _point_config_at(monkeypatch, "ex", root)
    monkeypatch.setenv("ST_CHECK_CHANGED_FILES", "mine.py\ntheirs.py")

    # Override path ignores lease scope (explicit file list wins).
    monkeypatch.delenv("ST_CHECK_LEASE_SCOPE", raising=False)
    assert check_changed._changed_files(root) == ["mine.py", "theirs.py"]


def test_lease_scope_enabled_truthy_values(monkeypatch):
    for val in ("1", "true", "YES", "on"):
        monkeypatch.setenv("ST_CHECK_LEASE_SCOPE", val)
        assert check_changed._lease_scope_enabled()
    for val in ("0", "", "off", "no"):
        monkeypatch.setenv("ST_CHECK_LEASE_SCOPE", val)
        assert not check_changed._lease_scope_enabled()
