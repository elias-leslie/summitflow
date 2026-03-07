"""Tests for live lane conflict checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.services.task_lane_preflight import check_task_lane_conflicts


def _mock_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class TestTaskLanePreflight:
    """Lane conflict detection."""

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_ownership_inventory_payload_maps_to_live_lane_sessions(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "project_id": "summitflow",
                "generated_at": "2026-03-07T18:00:00Z",
                "active_owners": [
                    {
                        "task_id": "task-999",
                        "session_id": "sess-ownership",
                        "branch": "task-999/main",
                        "worktree_path": "/tmp/worktrees/task-999",
                        "is_worktree": True,
                        "session_status": "active",
                        "workstream_status": "authoritative",
                        "ownership_kind": "scoped",
                        "scope_paths": ["backend/app/foo.py"],
                    }
                ],
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "worktree /tmp/worktrees/task-999" in result.suggestions[0]
        assert result.active_specialists == []

    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_ownership_inventory_payload_summarizes_active_specialists(
        self,
        mock_client_cls: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "project_id": "summitflow",
                "generated_at": "2026-03-07T18:00:00Z",
                "active_owners": [],
                "active_specialists": [
                    {
                        "session_id": "spec-1",
                        "agent_slug": "reviewer",
                        "project_id": "summitflow",
                        "request_source": "dispatch",
                        "age_minutes": 2,
                    },
                    {
                        "session_id": "spec-2",
                        "agent_slug": "reviewer",
                        "project_id": "summitflow",
                        "request_source": "dispatch",
                        "age_minutes": 5,
                    },
                ],
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.active_specialists == [
            {
                "agent_slug": "reviewer",
                "count": 2,
                "request_sources": ["dispatch"],
                "session_ids": ["spec-1", "spec-2"],
                "newest_age_minutes": 2,
                "oldest_age_minutes": 5,
            }
        ]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_ownership_endpoint_404_falls_back_to_legacy_sessions(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        not_found = _mock_response({})
        not_found.status_code = 404
        legacy = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-legacy",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/home/kasadis/summitflow",
                        "is_worktree": False,
                    }
                ]
            }
        )
        mock_client.get.side_effect = [not_found, legacy]
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "repo /home/kasadis/summitflow" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_same_task_active_lane_blocks_dispatch(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-1",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/worktrees/task-123",
                        "is_worktree": True,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert "active lane" in result.issues[0]
        assert "/tmp/worktrees/task-123" in result.issues[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_other_task_active_lane_blocks_parallel_dispatch(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-2",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/home/kasadis/summitflow",
                        "is_worktree": False,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "repo /home/kasadis/summitflow" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_branch_named_lane_blocks_when_external_id_missing(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-4",
                        "external_id": None,
                        "current_branch": "task-999/main",
                        "working_dir": "/tmp/worktrees/task-999",
                        "is_worktree": True,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues
        assert result.conflicting_tasks == ["task-999"]
        assert "worktree /tmp/worktrees/task-999" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_retired_workstream_does_not_block_dispatch(self, mock_client_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-3", "external_id": "task-999", "workstream_status": "retired"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_terminal_task_lane_is_ignored_even_if_session_is_active(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "blocked"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-5", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_same_task_stale_lane_points_to_reconcile_guidance(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-123", "status": "running"}
        stale_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-stale",
                        "external_id": "task-123",
                        "current_branch": "task-123/main",
                        "working_dir": "/tmp/worktrees/task-123",
                        "is_worktree": True,
                        "updated_at": stale_time,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert "likely stale active lane" in result.issues[0]
        assert "st sessions list --status active --project summitflow" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_other_task_stale_lane_updates_project_guidance(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        stale_time = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {
                        "id": "sess-stale-other",
                        "external_id": "task-999",
                        "current_branch": "task-999/main",
                        "working_dir": "/tmp/worktrees/task-999",
                        "is_worktree": True,
                        "updated_at": stale_time,
                    }
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert "likely stale active coding lane" in result.issues[0]
        assert result.conflicting_tasks == ["task-999"]
        assert "retire or reconcile it" in result.suggestions[1]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_disjoint_scoped_lanes_can_proceed(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-6", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.suggestions == []
        assert result.conflicting_tasks == []

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_exact_file_overlap_blocks_scoped_parallel_dispatch(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-7", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": [" ./backend/app/foo.py "]}}
            if task_id == "task-999":
                return {"context": {"files_to_create": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]
        assert result.overlap_kind == "exact_file"
        assert result.overlap_paths == ["backend/app/foo.py"]
        assert "backend/app/foo.py" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_shared_plumbing_overlap_blocks_adjacent_parallel_dispatch(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-7", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/services/tools/catalog.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/services/tools/tool_handler.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane is already modifying shared plumbing in project summitflow: "
            "task-999 (backend/app/services/tools/catalog.py, backend/app/services/tools/tool_handler.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]
        assert result.overlap_kind == "shared_plumbing"
        assert result.shared_plumbing is True
        assert "Do not run parallel coding lanes" in result.suggestions[0]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_non_shared_service_paths_do_not_trigger_shared_plumbing_block(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-7", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/services/reporting.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/services/runner.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.shared_plumbing is False

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_unscoped_active_lane_falls_back_to_project_block(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-8", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client
        mock_get_spirit.side_effect = [
            {"context": {"files_to_modify": ["backend/app/foo.py"]}},
            None,
        ]

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane exists in project summitflow but lacks usable file scope: task-999"
        ]
        assert result.conflicting_tasks == ["task-999"]
        assert any("scope unavailable" in suggestion for suggestion in result.suggestions)

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_malformed_scope_falls_back_to_project_block(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-9", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend//app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane exists in project summitflow but lacks usable file scope: task-999"
        ]
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_mixed_valid_and_invalid_scope_salvages_valid_paths(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-11", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py", "backend//bad.py", None]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": [" ./backend/app/foo.py ", ""]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_valid_scope_field_survives_other_malformed_scope_field(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-11", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {
                    "context": {
                        "files_to_modify": "backend/app/bad.py",
                        "files_to_create": ["backend/app/foo.py"],
                    }
                }
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_empty_or_invalid_only_scope_falls_back(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-12", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["", None, "backend//bad.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane exists in project summitflow but lacks usable file scope: task-123"
        ]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_absolute_scope_path_falls_back_to_project_block(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-10", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["/repo/backend/app/foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane exists in project summitflow but lacks usable file scope: task-123"
        ]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_path_matching_is_case_sensitive(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-10", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/Foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_multiple_equal_conflicts_choose_deterministic_task_id(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-aaa", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {"id": "sess-z", "external_id": "task-zzz", "current_branch": "task-zzz/main"},
                    {"id": "sess-a", "external_id": "task-aaa", "current_branch": "task-aaa/main"},
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id in {"task-aaa", "task-zzz"}:
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane overlaps exact files in project summitflow: task-aaa (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-aaa"]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_scoped_exact_overlap_wins_over_unscoped_lane(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-aaa", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {"id": "sess-a", "external_id": "task-aaa", "current_branch": "task-aaa/main"},
                    {"id": "sess-z", "external_id": "task-zzz", "current_branch": "task-zzz/main"},
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id == "task-aaa":
                return {}
            if task_id == "task-zzz":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding lane overlaps exact files in project summitflow: task-zzz (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-zzz"]

    @patch("app.services.task_lane_preflight.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    @patch("app.services.task_lane_preflight.httpx.Client")
    def test_unscoped_lane_is_ignored_when_other_lane_is_disjoint_and_scoped(
        self,
        mock_client_cls: MagicMock,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-aaa", "status": "running"}
        mock_client = MagicMock()
        mock_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {"id": "sess-a", "external_id": "task-aaa", "current_branch": "task-aaa/main"},
                    {"id": "sess-z", "external_id": "task-zzz", "current_branch": "task-zzz/main"},
                ]
            }
        )
        mock_client_cls.return_value.__enter__.return_value = mock_client

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id == "task-aaa":
                return {}
            if task_id == "task-zzz":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert result.conflicting_tasks == []
