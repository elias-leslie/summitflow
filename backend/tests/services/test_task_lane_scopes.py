"""Tests for scope validation and overlap detection in lane conflict checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.task_lane_preflight import check_task_lane_conflicts


def _mock_response(payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def mock_httpx_client(mocker):
    mock_client = MagicMock()
    mock_client_cls = mocker.patch("app.services._lane_inventory.httpx.Client")
    mock_client_cls.return_value.__enter__.return_value = mock_client
    return mock_client


class TestTaskLaneScopes:
    """Scope validation and file-overlap detection for parallel lane dispatch."""

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_disjoint_scoped_lanes_can_proceed(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-6", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

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

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_exact_file_overlap_blocks_scoped_parallel_dispatch(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-7", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": [" ./backend/app/foo.py "]}}
            if task_id == "task-999":
                return {"context": {"files_to_create": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]

        assert result.issues == [
            "Another active coding session overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]
        assert result.overlap_kind == "exact_file"
        assert result.overlap_paths == ["backend/app/foo.py"]
        assert "backend/app/foo.py" in result.suggestions[0]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_shared_plumbing_overlap_blocks_adjacent_parallel_dispatch(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-7", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/services/tools/catalog.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/services/tools/tool_handler.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session is already modifying shared plumbing in project summitflow: "
            "task-999 (backend/app/services/tools/catalog.py, backend/app/services/tools/tool_handler.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]
        assert result.overlap_kind == "shared_plumbing"
        assert result.shared_plumbing
        assert "Do not run parallel coding lanes" in result.suggestions[0]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_non_shared_service_paths_do_not_trigger_shared_plumbing_block(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-7", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/services/reporting.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/services/runner.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []
        assert not result.shared_plumbing

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_unscoped_active_lane_falls_back_to_project_block(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-8", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )
        mock_get_spirit.side_effect = [
            {"context": {"files_to_modify": ["backend/app/foo.py"]}},
            None,
        ]

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session exists in project summitflow but lacks usable file scope: task-999"
        ]
        assert result.conflicting_tasks == ["task-999"]
        assert any("scope unavailable" in suggestion for suggestion in result.suggestions)

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_malformed_scope_falls_back_to_project_block(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-9", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend//app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session exists in project summitflow but lacks usable file scope: task-999"
        ]
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_mixed_valid_and_invalid_scope_salvages_valid_paths(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-11", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py", "backend//bad.py", None]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": [" ./backend/app/foo.py ", ""]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_valid_scope_field_survives_other_malformed_scope_field(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-11", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

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
            "Another active coding session overlaps exact files in project summitflow: task-999 (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-999"]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_live_declared_scope_takes_precedence_over_task_spirit_fallback(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "project_id": "summitflow",
                "active_owners": [
                    {
                        "task_id": "task-999",
                        "session_id": "sess-12",
                        "branch": "task-999/main",
                        "checkout_path": "/tmp/lanes/task-999",
                        "session_status": "active",
                        "ownership_kind": "scoped",
                        "scope_paths": ["backend/app/ignored-by-live-scope.py"],
                        "declared_scope_paths": ["backend/app/foo.py"],
                        "observed_read_paths": [],
                        "observed_write_paths": ["backend/app/foo.py"],
                        "scope_confidence": "declared",
                    }
                ],
                "active_specialists": [],
            }
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.overlap_kind == "exact_file"
        assert result.overlap_paths == ["backend/app/foo.py"]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_live_read_overlap_warns_without_blocking(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "project_id": "summitflow",
                "active_owners": [
                    {
                        "task_id": "task-999",
                        "session_id": "sess-13",
                        "branch": "task-999/main",
                        "checkout_path": "/tmp/lanes/task-999",
                        "session_status": "active",
                        "ownership_kind": "scoped",
                        "declared_scope_paths": [],
                        "observed_read_paths": ["backend/app/foo.py"],
                        "observed_write_paths": [],
                        "scope_confidence": "observed_read",
                    }
                ],
                "active_specialists": [],
            }
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.disposition == "warn"
        assert result.overlap_kind == "read_overlap"
        assert result.overlap_paths == ["backend/app/foo.py"]
        assert result.issues == [
            "Another active coding session is reading files in the target scope in project summitflow: task-999 (backend/app/foo.py)"
        ]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_empty_or_invalid_only_scope_falls_back(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-12", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["", None, "backend//bad.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session exists in project summitflow but lacks usable file scope: task-123"
        ]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_absolute_scope_path_falls_back_to_project_block(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-10", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["/repo/backend/app/foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/bar.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session exists in project summitflow but lacks usable file scope: task-123"
        ]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_path_matching_is_case_sensitive(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-999", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {"sessions": [{"id": "sess-10", "external_id": "task-999", "current_branch": "task-999/main"}]}
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/Foo.py"]}}
            if task_id == "task-999":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == []

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_multiple_equal_conflicts_choose_deterministic_task_id(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-aaa", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {"id": "sess-z", "external_id": "task-zzz", "current_branch": "task-zzz/main"},
                    {"id": "sess-a", "external_id": "task-aaa", "current_branch": "task-aaa/main"},
                ]
            }
        )

        def _spirit(task_id: str) -> dict[str, object]:
            if task_id == "task-123":
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            if task_id in {"task-aaa", "task-zzz"}:
                return {"context": {"files_to_modify": ["backend/app/foo.py"]}}
            return {}

        mock_get_spirit.side_effect = _spirit

        result = check_task_lane_conflicts("task-123", "summitflow")

        assert result.issues == [
            "Another active coding session overlaps exact files in project summitflow: task-aaa (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-aaa"]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_scoped_exact_overlap_wins_over_unscoped_lane(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-aaa", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {"id": "sess-a", "external_id": "task-aaa", "current_branch": "task-aaa/main"},
                    {"id": "sess-z", "external_id": "task-zzz", "current_branch": "task-zzz/main"},
                ]
            }
        )

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
            "Another active coding session overlaps exact files in project summitflow: task-zzz (backend/app/foo.py)"
        ]
        assert result.conflicting_tasks == ["task-zzz"]

    @patch("app.services._lane_scope.get_task_spirit")
    @patch("app.services.task_lane_preflight.task_store.get_task")
    def test_unscoped_lane_is_ignored_when_other_lane_is_disjoint_and_scoped(
        self,
        mock_get_task: MagicMock,
        mock_get_spirit: MagicMock,
        mock_httpx_client: MagicMock,
    ) -> None:
        mock_get_task.return_value = {"id": "task-aaa", "status": "running"}
        mock_httpx_client.get.return_value = _mock_response(
            {
                "sessions": [
                    {"id": "sess-a", "external_id": "task-aaa", "current_branch": "task-aaa/main"},
                    {"id": "sess-z", "external_id": "task-zzz", "current_branch": "task-zzz/main"},
                ]
            }
        )

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
