from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from pytest_mock import MockerFixture

from app.storage.activity.sources.git import get_recent_git_events
from app.storage.activity.sources.tasks import get_recent_task_events


def _dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 4, 4, hour, minute, tzinfo=UTC)


def test_get_recent_task_events_tracks_created_updated_and_completed_tasks(
    mocker: MockerFixture,
) -> None:
    cursor = mocker.MagicMock()
    cursor.fetchall.return_value = [
        ("task-new", "summitflow", "Create public overview", "pending", None, _dt(12), _dt(12)),
        ("task-update", "summitflow", "Refine recent activity", "in_progress", None, _dt(13), _dt(11)),
        ("task-done", "summitflow", "Remove health tab", "completed", _dt(14), _dt(14), _dt(10)),
    ]
    cursor_manager = mocker.MagicMock()
    cursor_manager.__enter__.return_value = cursor
    cursor_manager.__exit__.return_value = False
    mocker.patch("app.storage.activity.sources.tasks.get_cursor", return_value=cursor_manager)

    events = get_recent_task_events("summitflow", limit=3)

    assert [event["message"] for event in events] == [
        "Task created: Create public overview",
        "Task updated: Refine recent activity",
        "Task completed: Remove health tab",
    ]
    assert [event["metadata"]["action"] for event in events] == ["created", "updated", "completed"]
    assert [event["metadata"]["status"] for event in events] == ["pending", "in_progress", "completed"]


def test_get_recent_git_events_uses_project_repo_history(
    mocker: MockerFixture,
) -> None:
    commit = SimpleNamespace(
        sha="abc1234567890",
        short_sha="abc1234",
        message="Fix project recent activity",
        author_name="Kas",
        repo_name="summitflow",
        date="2026-04-04T12:00:00+00:00",
        files_changed=4,
        insertions=20,
        deletions=5,
    )
    mocker.patch(
        "app.storage.activity.sources.git.get_project_root_path",
        return_value="/srv/workspaces/projects/summitflow",
    )
    mocker.patch("app.storage.activity.sources.git.get_recent_commits", return_value=[commit])

    events = get_recent_git_events("summitflow", limit=5)

    assert events == [
        {
            "type": "git",
            "message": "Commit abc1234: Fix project recent activity",
            "timestamp": "2026-04-04T12:00:00+00:00",
            "project_id": "summitflow",
            "metadata": {
                "commit_sha": "abc1234567890",
                "repo_name": "summitflow",
                "author_name": "Kas",
                "files_changed": 4,
                "insertions": 20,
                "deletions": 5,
            },
        }
    ]


def test_get_recent_git_events_merges_managed_repo_history(
    mocker: MockerFixture,
) -> None:
    repo_a = Path("/srv/workspaces/projects/summitflow")
    repo_b = Path("/srv/workspaces/projects/agent-hub")
    commit_a = SimpleNamespace(
        sha="aaa1111",
        short_sha="aaa1111",
        message="Older summitflow commit",
        author_name="Kas",
        repo_name="summitflow",
        date="2026-04-04T11:00:00+00:00",
        files_changed=1,
        insertions=2,
        deletions=0,
    )
    commit_b = SimpleNamespace(
        sha="bbb2222",
        short_sha="bbb2222",
        message="Newer agent-hub commit",
        author_name="Kas",
        repo_name="agent-hub",
        date="2026-04-04T12:00:00+00:00",
        files_changed=3,
        insertions=5,
        deletions=1,
    )
    mocker.patch("app.storage.activity.sources.git.get_managed_repos", return_value=[repo_a, repo_b])
    mocker.patch(
        "app.storage.activity.sources.git._resolve_project_id",
        side_effect=["summitflow", "agent-hub"],
    )
    mocker.patch(
        "app.storage.activity.sources.git.get_recent_commits",
        side_effect=[[commit_a], [commit_b]],
    )

    events = get_recent_git_events(limit=1)

    assert events == [
        {
            "type": "git",
            "message": "Commit bbb2222: Newer agent-hub commit",
            "timestamp": "2026-04-04T12:00:00+00:00",
            "project_id": "agent-hub",
            "metadata": {
                "commit_sha": "bbb2222",
                "repo_name": "agent-hub",
                "author_name": "Kas",
                "files_changed": 3,
                "insertions": 5,
                "deletions": 1,
            },
        }
    ]
