"""Tests for per-project quality gate configuration."""

from __future__ import annotations

from unittest.mock import patch

from app.services.quality_gate.escalation import get_escalation_level
from app.storage.agent_configs import DEFAULT_AGENT_CONFIG, AgentConfig
from app.storage.agent_configs_quality import (
    build_dt_command,
    get_quality_gate_fix_enabled,
    get_quality_gate_mode,
    get_quality_gate_tools,
)


class TestGetQualityGateTools:
    """Tests for get_quality_gate_tools function."""

    def test_get_quality_gate_tools_returns_empty_list_when_not_configured(self) -> None:
        """Test get_quality_gate_tools returns empty list when quality_gate_tools is not set."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        # quality_gate_tools defaults to [] in DEFAULT_AGENT_CONFIG

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_tools("test-project")

        # Assert
        assert result == []

    def test_get_quality_gate_tools_returns_configured_tools(self) -> None:
        """Test get_quality_gate_tools returns configured tool list."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = ["ruff", "types"]

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_tools("test-project")

        # Assert
        assert result == ["ruff", "types"]

    def test_get_quality_gate_tools_converts_non_strings(self) -> None:
        """Test get_quality_gate_tools converts items to strings."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        # Simulate config with non-string values (edge case)
        config["quality_gate_tools"] = ["ruff", 123]  # type: ignore[list-item]

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_tools("test-project")

        # Assert
        assert result == ["ruff", "123"]

    def test_get_quality_gate_tools_returns_empty_when_not_a_list(self) -> None:
        """Test get_quality_gate_tools returns empty list when value is not a list."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = "ruff"  # type: ignore[typeddict-item]

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_tools("test-project")

        # Assert
        assert result == []


class TestGetQualityGateMode:
    """Tests for get_quality_gate_mode function."""

    def test_get_quality_gate_mode_returns_quick_when_not_configured(self) -> None:
        """Test get_quality_gate_mode returns 'quick' by default."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        # quality_gate_mode defaults to "quick" in DEFAULT_AGENT_CONFIG

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_mode("test-project")

        # Assert
        assert result == "quick"

    def test_get_quality_gate_mode_returns_check_when_configured(self) -> None:
        """Test get_quality_gate_mode returns 'check' when configured."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_mode"] = "check"

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_mode("test-project")

        # Assert
        assert result == "check"

    def test_get_quality_gate_mode_returns_changed_only_when_configured(self) -> None:
        """Test get_quality_gate_mode returns 'changed-only' when configured."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_mode"] = "changed-only"

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_mode("test-project")

        # Assert
        assert result == "changed-only"

    def test_get_quality_gate_mode_returns_quick_for_invalid_mode(self) -> None:
        """Test get_quality_gate_mode returns 'quick' for invalid mode."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_mode"] = "invalid-mode"

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_mode("test-project")

        # Assert
        assert result == "quick"


class TestGetQualityGateFixEnabled:
    """Tests for get_quality_gate_fix_enabled function."""

    def test_get_quality_gate_fix_enabled_returns_true_by_default(self) -> None:
        """Test get_quality_gate_fix_enabled returns True by default."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        # quality_gate_fix_enabled defaults to True in DEFAULT_AGENT_CONFIG

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_fix_enabled("test-project")

        # Assert
        assert result

    def test_get_quality_gate_fix_enabled_returns_false_when_disabled(self) -> None:
        """Test get_quality_gate_fix_enabled returns False when disabled."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_fix_enabled"] = False

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = get_quality_gate_fix_enabled("test-project")

        # Assert
        assert not result


class TestBuildDtCommand:
    """Tests for build_dt_command function."""

    def test_build_dt_command_with_empty_tools_returns_quick_mode(self) -> None:
        """Test build_dt_command with empty tools list returns dt --quick (default mode)."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = []
        config["quality_gate_mode"] = "quick"

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project")

        # Assert
        assert result == ["dt", "--quick"]

    def test_build_dt_command_with_specific_tools_returns_tools(self) -> None:
        """Test build_dt_command with specific tools returns dt ruff types."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = ["ruff", "types"]

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project")

        # Assert
        assert result == ["dt", "ruff", "types"]

    def test_build_dt_command_with_fix_true_and_fix_enabled_returns_fix_flag(self) -> None:
        """Test build_dt_command with fix=True and fix enabled returns dt ruff --fix."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = ["ruff"]
        config["quality_gate_fix_enabled"] = True

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project", fix=True)

        # Assert
        assert result == ["dt", "ruff", "--fix"]

    def test_build_dt_command_with_fix_true_and_fix_disabled_falls_back_to_check(self) -> None:
        """Test build_dt_command with fix=True and fix disabled falls back to check mode."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = ["ruff"]
        config["quality_gate_fix_enabled"] = False

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project", fix=True)

        # Assert
        assert result == ["dt", "ruff"]

    def test_build_dt_command_with_mode_check_returns_check_flag(self) -> None:
        """Test build_dt_command with mode='check' returns dt --check."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = []
        config["quality_gate_mode"] = "check"

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project")

        # Assert
        assert result == ["dt", "--check"]

    def test_build_dt_command_with_mode_changed_only_returns_changed_only_flag(self) -> None:
        """Test build_dt_command with mode='changed-only' returns dt --changed-only."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = []
        config["quality_gate_mode"] = "changed-only"

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project")

        # Assert
        assert result == ["dt", "--changed-only"]

    def test_build_dt_command_with_fix_true_no_tools_returns_dt_fix(self) -> None:
        """Test build_dt_command with fix=True and no tools returns dt --fix."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = []
        config["quality_gate_fix_enabled"] = True

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project", fix=True)

        # Assert
        assert result == ["dt", "--fix"]

    def test_build_dt_command_with_multiple_tools(self) -> None:
        """Test build_dt_command with multiple tools returns all tools."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = ["ruff", "types", "biome", "tsc"]

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("dt", "test-project")

        # Assert
        assert result == ["dt", "ruff", "types", "biome", "tsc"]

    def test_build_dt_command_with_custom_dt_path(self) -> None:
        """Test build_dt_command uses provided dt path."""
        # Arrange
        config: AgentConfig = DEFAULT_AGENT_CONFIG.copy()
        config["quality_gate_tools"] = ["ruff"]

        # Act
        with patch("app.storage.agent_configs_quality.get_agent_config", return_value=config):
            result = build_dt_command("/usr/local/bin/dt", "test-project")

        # Assert
        assert result == ["/usr/local/bin/dt", "ruff"]


class TestGetEscalationLevel:
    """Tests for get_escalation_level function with per-project thresholds."""

    def test_get_escalation_level_with_project_id_reads_per_project_thresholds(self) -> None:
        """Test get_escalation_level with project_id reads per-project thresholds."""
        # Arrange
        worker_attempts = 5
        supervisor_attempts = 3

        # Act & Assert
        with patch("app.services.quality_gate.escalation.get_max_self_fix_attempts", return_value=worker_attempts), \
             patch("app.services.quality_gate.escalation.get_max_supervisor_attempts", return_value=supervisor_attempts):
            # Worker level (attempts 0-4, i.e., < 5)
            assert get_escalation_level(0, "test-project") == "WORKER"
            assert get_escalation_level(4, "test-project") == "WORKER"

            # Supervisor level (attempts 5-7, i.e., < 5+3)
            assert get_escalation_level(5, "test-project") == "SUPERVISOR"
            assert get_escalation_level(7, "test-project") == "SUPERVISOR"

            # Escalate level (attempts >= 8, i.e., >= 5+3)
            assert get_escalation_level(8, "test-project") == "ESCALATE"
            assert get_escalation_level(10, "test-project") == "ESCALATE"

    def test_get_escalation_level_without_project_id_uses_hardcoded_defaults(self) -> None:
        """Test get_escalation_level without project_id uses hardcoded defaults (backward compat)."""
        # Act & Assert
        # Default thresholds: WORKER_ATTEMPTS=3, SUPERVISOR_ATTEMPTS=2, MAX=5

        # Worker level (attempts 0-2, i.e., < 3)
        assert get_escalation_level(0) == "WORKER"
        assert get_escalation_level(2) == "WORKER"

        # Supervisor level (attempts 3-4, i.e., < 5)
        assert get_escalation_level(3) == "SUPERVISOR"
        assert get_escalation_level(4) == "SUPERVISOR"

        # Escalate level (attempts >= 5)
        assert get_escalation_level(5) == "ESCALATE"
        assert get_escalation_level(10) == "ESCALATE"

    def test_get_escalation_level_with_project_id_custom_thresholds(self) -> None:
        """Test get_escalation_level with custom per-project thresholds."""
        # Arrange
        worker_attempts = 2
        supervisor_attempts = 1

        # Act & Assert
        with patch("app.services.quality_gate.escalation.get_max_self_fix_attempts", return_value=worker_attempts), \
             patch("app.services.quality_gate.escalation.get_max_supervisor_attempts", return_value=supervisor_attempts):
            # Worker level (attempts 0-1, i.e., < 2)
            assert get_escalation_level(0, "test-project") == "WORKER"
            assert get_escalation_level(1, "test-project") == "WORKER"

            # Supervisor level (attempts 2, i.e., < 2+1=3)
            assert get_escalation_level(2, "test-project") == "SUPERVISOR"

            # Escalate level (attempts >= 3)
            assert get_escalation_level(3, "test-project") == "ESCALATE"

    def test_get_escalation_level_with_zero_supervisor_attempts(self) -> None:
        """Test get_escalation_level with zero supervisor attempts."""
        # Arrange
        worker_attempts = 3
        supervisor_attempts = 0

        # Act & Assert
        with patch("app.services.quality_gate.escalation.get_max_self_fix_attempts", return_value=worker_attempts), \
             patch("app.services.quality_gate.escalation.get_max_supervisor_attempts", return_value=supervisor_attempts):
            # Worker level (attempts 0-2, i.e., < 3)
            assert get_escalation_level(0, "test-project") == "WORKER"
            assert get_escalation_level(2, "test-project") == "WORKER"

            # Escalate level immediately after worker (attempts >= 3)
            assert get_escalation_level(3, "test-project") == "ESCALATE"
