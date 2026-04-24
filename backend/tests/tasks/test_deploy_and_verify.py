"""Tests for auto-deploy after merge (_deploy_and_verify)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.smoke_test import HEALTH_URLS
from app.tasks.autonomous.review_modules.actions import (
    _deploy_and_verify,
    auto_merge,
)


class TestDeployAndVerify:
    """Tests for _deploy_and_verify function."""

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.subprocess.run")
    @patch("app.tasks.autonomous.review_modules.actions.get_project_root_path")
    def test_successful_deploy_and_verify(
        self,
        mock_root: MagicMock,
        mock_run: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_root.return_value = "/home/user/summitflow"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # st service rebuild
            MagicMock(returncode=0),  # cf-curl
        ]

        _deploy_and_verify("task-1", "summitflow")

        assert mock_run.call_count == 2
        assert mock_log.call_count == 2
        mock_log.assert_any_call("task-1", "Auto-deploy: st service rebuild succeeded")
        mock_log.assert_any_call(
            "task-1", f"Production verified: {HEALTH_URLS['summitflow']}"
        )

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.get_project_root_path")
    def test_no_project_root_returns_early(
        self, mock_root: MagicMock, mock_log: MagicMock
    ) -> None:
        mock_root.return_value = None

        _deploy_and_verify("task-1", "summitflow")

        mock_log.assert_not_called()

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.subprocess.run")
    @patch("app.tasks.autonomous.review_modules.actions.get_project_root_path")
    def test_rebuild_failure_logs_error(
        self,
        mock_root: MagicMock,
        mock_run: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_root.return_value = "/home/user/summitflow"
        mock_run.return_value = MagicMock(returncode=1, stderr="build failed")

        _deploy_and_verify("task-1", "summitflow")

        mock_log.assert_called_once()
        assert "Auto-deploy failed" in mock_log.call_args[0][1]

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.subprocess.run")
    @patch("app.tasks.autonomous.review_modules.actions.get_project_root_path")
    def test_rebuild_timeout_logs_error(
        self,
        mock_root: MagicMock,
        mock_run: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        import subprocess

        mock_root.return_value = "/home/user/summitflow"
        mock_run.side_effect = subprocess.TimeoutExpired("rebuild.sh", 300)

        _deploy_and_verify("task-1", "summitflow")

        mock_log.assert_called_once()
        assert "Auto-deploy failed" in mock_log.call_args[0][1]

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.subprocess.run")
    @patch("app.tasks.autonomous.review_modules.actions.get_project_root_path")
    def test_health_check_failure_logs_warning(
        self,
        mock_root: MagicMock,
        mock_run: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_root.return_value = "/home/user/summitflow"
        mock_run.side_effect = [
            MagicMock(returncode=0),  # st service rebuild succeeds
            MagicMock(returncode=1),  # cf-curl fails
        ]

        _deploy_and_verify("task-1", "summitflow")

        # Should log success for rebuild + warning for health
        assert mock_log.call_count == 2
        last_call = mock_log.call_args_list[-1]
        assert "Production check failed" in last_call[0][1]
        assert last_call[1]["level"] == "warning"

    @patch("app.tasks.autonomous.review_modules.actions.log_task_event")
    @patch("app.tasks.autonomous.review_modules.actions.subprocess.run")
    @patch("app.tasks.autonomous.review_modules.actions.get_project_root_path")
    def test_unknown_project_skips_health_check(
        self,
        mock_root: MagicMock,
        mock_run: MagicMock,
        mock_log: MagicMock,
    ) -> None:
        mock_root.return_value = "/home/user/unknown"
        mock_run.return_value = MagicMock(returncode=0)

        _deploy_and_verify("task-1", "unknown-project")

        # Only rebuild runs, no health check
        assert mock_run.call_count == 1
        mock_log.assert_called_once_with("task-1", "Auto-deploy: st service rebuild succeeded")


class TestAutoMergeDeployIntegration:
    """Tests that auto_merge calls _deploy_and_verify on success."""

    @patch("app.tasks.autonomous.review_modules.actions._deploy_and_verify")
    @patch("app.tasks.autonomous.cleanup.merge_and_cleanup_task_checkpoint")
    @patch("app.tasks.autonomous.review_modules.actions.task_store")
    def test_deploy_called_on_successful_merge(
        self,
        mock_store: MagicMock,
        mock_merge: MagicMock,
        mock_deploy: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "summitflow"}
        mock_merge.return_value = {"status": "merged", "post_merge_valid": True}

        auto_merge("task-1")

        mock_deploy.assert_called_once_with("task-1", "summitflow")

    @patch("app.tasks.autonomous.review_modules.actions._deploy_and_verify")
    @patch("app.tasks.autonomous.cleanup.merge_and_cleanup_task_checkpoint")
    @patch("app.tasks.autonomous.review_modules.actions.task_store")
    def test_deploy_not_called_on_failed_merge(
        self,
        mock_store: MagicMock,
        mock_merge: MagicMock,
        mock_deploy: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "summitflow"}
        mock_merge.return_value = {"status": "error", "error": "conflict"}

        auto_merge("task-1")

        mock_deploy.assert_not_called()

    @patch("app.tasks.autonomous.review_modules.actions._deploy_and_verify")
    @patch("app.tasks.autonomous.cleanup.merge_and_cleanup_task_checkpoint")
    @patch("app.tasks.autonomous.review_modules.actions.task_store")
    def test_deploy_not_called_on_validation_failure(
        self,
        mock_store: MagicMock,
        mock_merge: MagicMock,
        mock_deploy: MagicMock,
    ) -> None:
        mock_store.get_task.return_value = {"project_id": "summitflow"}
        mock_merge.return_value = {"status": "merged", "post_merge_valid": False}

        auto_merge("task-1")

        mock_deploy.assert_not_called()
