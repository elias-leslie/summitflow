"""Tests for the file-lease primitive.

Focused regression coverage for the bugs caught by the lease-hook wargame.
"""

from __future__ import annotations

import pytest

from cli.lib import leases


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    """Redirect lease storage to a tmp dir so tests don't see real leases."""
    monkeypatch.setattr(leases, "LEASES_DIR", tmp_path / "leases")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "")
    return tmp_path


def test_relative_glob_resolves_against_project_root(isolated_store, monkeypatch):
    """Wargame repro: `st lease 'docs/X.md'` must block edits to the absolute path.

    Before the fix, acquire stored the glob verbatim ("docs/X.md") and the
    hook checked the absolute path ("/srv/.../docs/X.md") — fnmatch missed,
    edits silently bypassed the gate.
    """
    project_root = "/srv/workspaces/projects/example"
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    lease = leases.acquire(
        project_id="example",
        globs=["docs/README.md"],
        project_root=project_root,
    )
    assert lease.globs == [f"{project_root}/docs/README.md"]

    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    ok, holder = leases.check("example", f"{project_root}/docs/README.md")
    assert not ok
    assert holder is not None
    assert holder.agent_id.startswith("cc:alice")


def test_absolute_glob_unchanged(isolated_store, monkeypatch):
    """Absolute globs must pass through acquire unmodified."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    abs_path = "/srv/workspaces/projects/example/app/api/foo.py"
    lease = leases.acquire(
        project_id="example",
        globs=[abs_path],
        project_root="/srv/workspaces/projects/example",
    )
    assert lease.globs == [abs_path]


def test_same_agent_same_globs_extends_heartbeat(isolated_store, monkeypatch):
    """Re-acquire with identical globs must refresh, not duplicate."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    first = leases.acquire(
        project_id="example",
        globs=["docs/README.md"],
        project_root="/srv/workspaces/projects/example",
    )
    second = leases.acquire(
        project_id="example",
        globs=["docs/README.md"],
        project_root="/srv/workspaces/projects/example",
    )
    assert first.lease_id == second.lease_id
    assert len(leases.list_active("example")) == 1


def test_check_returns_ok_for_unmanaged_path(isolated_store, monkeypatch):
    """Paths not covered by any lease are free regardless of project root."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire(
        project_id="example",
        globs=["app/api/**"],
        project_root="/srv/workspaces/projects/example",
    )

    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    ok, holder = leases.check(
        "example", "/srv/workspaces/projects/example/docs/README.md"
    )
    assert ok
    assert holder is None
