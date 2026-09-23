"""Tests for the file-lease primitive.

Focused regression coverage for the bugs caught by the lease-hook wargame.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from cli.commands import lease as lease_command
from cli.lib import leases

runner = CliRunner()


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


def test_release_task_drops_all_holders(isolated_store, monkeypatch):
    """st done closeout: every lease for a task is released, even one held by a
    subagent under a different agent identity than the closer."""
    root = "/srv/workspaces/projects/example"
    monkeypatch.setenv("CLAUDE_SESSION_ID", "subagent-a")
    leases.acquire("example", ["app/a.py"], task_id="T1", project_root=root)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "subagent-b")
    leases.acquire("example", ["app/b.py"], task_id="T1", project_root=root)
    assert len(leases.list_active("example")) == 2

    # Orchestrator (yet another identity) closes the task.
    monkeypatch.setenv("CLAUDE_SESSION_ID", "orchestrator")
    released = leases.release_task("example", "T1")
    assert released == 2
    assert leases.list_active("example") == []


def test_release_task_leaves_other_tasks(isolated_store, monkeypatch):
    """Releasing one task's leases must not touch another task's leases."""
    root = "/srv/workspaces/projects/example"
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["app/a.py"], task_id="T1", project_root=root)
    leases.acquire("example", ["app/b.py"], task_id="T2", project_root=root)

    released = leases.release_task("example", "T1")
    assert released == 1
    remaining = leases.list_active("example")
    assert [lease.task_id for lease in remaining] == ["T2"]


def test_release_task_empty_id_is_noop(isolated_store, monkeypatch):
    """A blank task id releases nothing (defensive: never wipe untagged leases)."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["app/a.py"], project_root="/srv/workspaces/projects/example")
    assert leases.release_task("example", "") == 0
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


def test_cli_relative_check_blocks_other_agent(isolated_store, monkeypatch):
    root = str(isolated_store / "example")
    monkeypatch.setattr(lease_command, "_resolve_project", lambda: ("example", root))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["docs/README.md"], project_root=root)

    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    result = runner.invoke(lease_command.app, ["lease", "--check", "docs/README.md"])
    assert result.exit_code == 2
    assert "BLOCKED" in result.output


def test_check_rejects_foreign_overlap_even_when_own_lease_matches(
    isolated_store, monkeypatch
):
    root = str(isolated_store / "example")
    path = f"{root}/docs/README.md"
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["docs/README.md"], project_root=root)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    leases.acquire("example", ["docs/**"], project_root=root)

    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    ok, holder = leases.check("example", path)
    assert not ok
    assert holder is not None
    assert holder.agent_id == "cc:bob"


def test_lease_check_does_not_block_other_projects(isolated_store, monkeypatch):
    root = str(isolated_store / "example")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["docs/README.md"], project_root=root)

    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    assert leases.check("another-project", f"{root}/docs/README.md") == (True, None)


def test_relative_take_and_release_use_project_root(isolated_store, monkeypatch):
    root = str(isolated_store / "example")
    monkeypatch.setattr(lease_command, "_resolve_project", lambda: ("example", root))
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["docs/README.md"], project_root=root)

    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    taken = runner.invoke(lease_command.app, ["lease", "--take", "docs/README.md"])
    assert taken.exit_code == 0
    assert [(lease.agent_id, lease.globs) for lease in leases.list_active("example")] == [
        ("cc:bob", [f"{root}/docs/README.md"])
    ]

    released = runner.invoke(lease_command.app, ["lease", "--release", "docs/README.md"])
    assert released.exit_code == 0
    assert leases.list_active("example") == []


def test_relative_wait_observes_foreign_lease(isolated_store, monkeypatch):
    root = str(isolated_store / "example")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "alice")
    leases.acquire("example", ["docs/README.md"], project_root=root)

    monkeypatch.setenv("CLAUDE_SESSION_ID", "bob")
    assert not leases.wait(
        "example", "docs/README.md", timeout=0.01, poll=0.02, project_root=root
    )
