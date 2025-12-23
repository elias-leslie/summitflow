"""Unit tests for memory opt-out functionality."""

from unittest.mock import patch

import pytest


class TestIsMemoryFeatureEnabled:
    """Tests for is_memory_feature_enabled function."""

    @patch("app.storage.agent_configs.get_agent_config")
    def test_enabled_when_all_true(self, mock_get_config):
        """Feature enabled when both master and feature flag are true."""
        from app.storage.agent_configs import is_memory_feature_enabled

        mock_get_config.return_value = {
            "memory_enabled": True,
            "observations_enabled": True,
        }
        assert is_memory_feature_enabled("test-project", "observations") is True

    @patch("app.storage.agent_configs.get_agent_config")
    def test_disabled_when_master_false(self, mock_get_config):
        """Feature disabled when master switch is false."""
        from app.storage.agent_configs import is_memory_feature_enabled

        mock_get_config.return_value = {
            "memory_enabled": False,
            "observations_enabled": True,  # Feature enabled but master off
        }
        assert is_memory_feature_enabled("test-project", "observations") is False

    @patch("app.storage.agent_configs.get_agent_config")
    def test_disabled_when_feature_false(self, mock_get_config):
        """Feature disabled when feature-specific flag is false."""
        from app.storage.agent_configs import is_memory_feature_enabled

        mock_get_config.return_value = {
            "memory_enabled": True,
            "observations_enabled": False,
        }
        assert is_memory_feature_enabled("test-project", "observations") is False

    @patch("app.storage.agent_configs.get_agent_config")
    def test_defaults_to_true_when_missing(self, mock_get_config):
        """Defaults to True when config keys are missing."""
        from app.storage.agent_configs import is_memory_feature_enabled

        mock_get_config.return_value = {}
        assert is_memory_feature_enabled("test-project", "observations") is True

    @patch("app.storage.agent_configs.get_agent_config")
    def test_all_feature_types(self, mock_get_config):
        """All feature types work correctly."""
        from app.storage.agent_configs import is_memory_feature_enabled

        mock_get_config.return_value = {
            "memory_enabled": True,
            "observations_enabled": True,
            "diary_enabled": False,
            "patterns_enabled": True,
            "checkpoints_enabled": False,
            "context_injection_enabled": True,
        }

        assert is_memory_feature_enabled("test", "observations") is True
        assert is_memory_feature_enabled("test", "diary") is False
        assert is_memory_feature_enabled("test", "patterns") is True
        assert is_memory_feature_enabled("test", "checkpoints") is False
        assert is_memory_feature_enabled("test", "context_injection") is True


class TestGetMemoryConfig:
    """Tests for get_memory_config function."""

    @patch("app.storage.agent_configs.get_agent_config")
    def test_returns_all_memory_flags(self, mock_get_config):
        """Returns dict with all memory flags."""
        from app.storage.agent_configs import get_memory_config

        mock_get_config.return_value = {
            "memory_enabled": True,
            "observations_enabled": False,
            "diary_enabled": True,
            "patterns_enabled": False,
            "checkpoints_enabled": True,
            "context_injection_enabled": False,
        }

        config = get_memory_config("test-project")

        assert config == {
            "memory_enabled": True,
            "observations_enabled": False,
            "diary_enabled": True,
            "patterns_enabled": False,
            "checkpoints_enabled": True,
            "context_injection_enabled": False,
        }

    @patch("app.storage.agent_configs.get_agent_config")
    def test_defaults_when_empty(self, mock_get_config):
        """Returns defaults when config is empty."""
        from app.storage.agent_configs import get_memory_config

        mock_get_config.return_value = {}

        config = get_memory_config("test-project")

        # All should default to True
        assert all(v is True for v in config.values())
        assert "memory_enabled" in config
        assert "observations_enabled" in config


class TestStorageGuards:
    """Tests for storage layer guards returning None when disabled."""

    @patch("app.storage.agent_configs.is_memory_feature_enabled")
    def test_create_queue_item_returns_none_when_disabled(self, mock_enabled):
        """create_queue_item returns None when observations disabled."""
        from app.storage.memory import create_queue_item

        mock_enabled.return_value = False

        result = create_queue_item(
            project_id="test",
            session_id="session-123",
            agent_type="claude",
            tool_name="Write",
            tool_output="test output",
        )

        assert result is None

    @patch("app.storage.agent_configs.is_memory_feature_enabled")
    def test_create_observation_returns_none_when_disabled(self, mock_enabled):
        """create_observation returns None when observations disabled."""
        from app.storage.memory import create_observation

        mock_enabled.return_value = False

        result = create_observation(
            project_id="test",
            session_id="session-123",
            agent_type="claude",
            observation_type="discovery",
            title="Test observation",
        )

        assert result is None

    @patch("app.storage.agent_configs.is_memory_feature_enabled")
    def test_create_diary_entry_returns_none_when_disabled(self, mock_enabled):
        """create_diary_entry returns None when diary disabled."""
        from app.storage.memory import create_diary_entry

        mock_enabled.return_value = False

        result = create_diary_entry(
            project_id="test",
            session_id="session-123",
            agent_type="claude",
            outcome="success",
        )

        assert result is None

    @patch("app.storage.agent_configs.is_memory_feature_enabled")
    def test_create_pattern_returns_none_when_disabled(self, mock_enabled):
        """create_pattern returns None when patterns disabled."""
        from app.storage.memory import create_pattern

        mock_enabled.return_value = False

        result = create_pattern(
            project_id="test",
            pattern_type="workflow",
            title="Test pattern",
            content="Test content",
        )

        assert result is None

    @patch("app.storage.agent_configs.is_memory_feature_enabled")
    def test_create_checkpoint_returns_none_when_disabled(self, mock_enabled):
        """create_checkpoint returns None when checkpoints disabled."""
        from app.storage.memory import create_checkpoint

        mock_enabled.return_value = False

        result = create_checkpoint(
            project_id="test",
            session_id="session-123",
            agent_type="claude",
        )

        assert result is None


class TestSkipMemoryCheckBypass:
    """Tests for skip_memory_check parameter bypassing guards."""

    @patch("app.storage.agent_configs.is_memory_feature_enabled")
    def test_skip_flag_bypasses_guard(self, mock_enabled):
        """skip_memory_check=True bypasses the feature check (verified by mock not called)."""
        from app.storage.memory import create_queue_item

        mock_enabled.return_value = False  # Would return None normally

        # When we call with skip_memory_check=True and memory disabled,
        # we should verify the guard is bypassed (function proceeds to DB call)
        # Since we don't want to hit the real DB, we verify the mock wasn't called
        # Actually with skip_memory_check=True, is_memory_feature_enabled should NOT be called

        # Reset the mock
        mock_enabled.reset_mock()

        # This will fail at DB layer, but that's OK - we're testing the guard bypass
        try:
            create_queue_item(
                project_id="test",
                session_id="session-123",
                agent_type="claude",
                tool_name="Write",
                skip_memory_check=True,  # Should bypass
            )
        except Exception:
            # Expected to fail at DB layer
            pass

        # Key assertion: is_memory_feature_enabled should NOT have been called
        mock_enabled.assert_not_called()
