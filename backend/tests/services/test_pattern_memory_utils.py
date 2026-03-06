"""Tests for project-scoped quality-gate pattern memory utilities."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.quality_gate import pattern_memory_utils as pmu


class TestPatternMemoryUtils:
    def setup_method(self) -> None:
        pmu._pattern_memory_by_project.clear()

    def test_get_pattern_memory_caches_per_project(self) -> None:
        with patch.object(pmu, "PatternMemoryService") as mock_service:
            first = MagicMock(name="first")
            second = MagicMock(name="second")
            mock_service.side_effect = [first, second]

            alpha_one = pmu._get_pattern_memory("alpha")
            alpha_two = pmu._get_pattern_memory("alpha")
            beta_one = pmu._get_pattern_memory("beta")

        assert alpha_one is first
        assert alpha_two is first
        assert beta_one is second
        assert mock_service.call_args_list[0].kwargs == {"project_id": "alpha"}
        assert mock_service.call_args_list[1].kwargs == {"project_id": "beta"}

    def test_get_similar_patterns_uses_requested_project_scope(self) -> None:
        pattern_service = MagicMock()
        pattern_service.get_similar_patterns = AsyncMock(return_value=[])

        with patch.object(pmu, "_get_pattern_memory", return_value=pattern_service) as mock_get:
            patterns = pmu.get_similar_patterns(
                "ruff",
                "F401",
                "unused import",
                project_id="agent-hub",
            )

        assert patterns == []
        mock_get.assert_called_once_with("agent-hub")
        pattern_service.get_similar_patterns.assert_awaited_once()

    def test_store_successful_pattern_uses_requested_project_scope(self) -> None:
        pattern_service = MagicMock()
        pattern_service.store_fix_pattern = AsyncMock(return_value={"success": True})

        with patch.object(pmu, "_get_pattern_memory", return_value=pattern_service) as mock_get:
            pmu.store_successful_pattern(
                check_type="ruff",
                check_name="F401",
                error_message="unused import",
                file_path="test.py",
                original_content="import os\n",
                fixed_content="",
                project_id="agent-hub",
            )

        mock_get.assert_called_once_with("agent-hub")
        pattern_service.store_fix_pattern.assert_awaited_once()
