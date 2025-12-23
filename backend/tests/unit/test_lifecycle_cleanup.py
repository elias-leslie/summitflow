"""Unit tests for memory lifecycle cleanup functions."""

from __future__ import annotations

import uuid

from app.storage.memory import (
    _compute_observation_hash,
    archive_failed_queue_items,
    cleanup_old_checkpoints,
    create_observation,
    get_lifecycle_stats,
    reset_stuck_queue_items,
)


class TestGetLifecycleStats:
    """Tests for get_lifecycle_stats function."""

    def test_returns_expected_shape(self) -> None:
        """Test that get_lifecycle_stats returns dict with expected keys."""
        stats = get_lifecycle_stats()

        assert "failed_queue_count" in stats
        assert "stuck_queue_count" in stats
        assert "oldest_pending_age_minutes" in stats
        assert "unreflected_diary_count" in stats
        assert "stale_patterns_count" in stats
        assert "pattern_status_breakdown" in stats

        assert isinstance(stats["failed_queue_count"], int)
        assert isinstance(stats["stuck_queue_count"], int)
        assert isinstance(stats["unreflected_diary_count"], int)
        assert isinstance(stats["stale_patterns_count"], int)
        assert isinstance(stats["pattern_status_breakdown"], dict)

    def test_supports_project_filter(self) -> None:
        """Test that project_id filter is accepted."""
        stats = get_lifecycle_stats(project_id="summitflow")
        assert isinstance(stats, dict)


class TestCleanupFunctions:
    """Tests for cleanup storage functions."""

    def test_archive_failed_queue_items_returns_int(self) -> None:
        """Test archive_failed_queue_items returns deleted count."""
        result = archive_failed_queue_items(max_age_days=14)
        assert isinstance(result, int)
        assert result >= 0

    def test_cleanup_old_checkpoints_returns_int(self) -> None:
        """Test cleanup_old_checkpoints returns deleted count."""
        result = cleanup_old_checkpoints(max_age_days=30)
        assert isinstance(result, int)
        assert result >= 0

    def test_reset_stuck_queue_items_returns_int(self) -> None:
        """Test reset_stuck_queue_items returns reset count."""
        result = reset_stuck_queue_items(threshold_minutes=60)
        assert isinstance(result, int)
        assert result >= 0


class TestObservationDeduplication:
    """Tests for observation deduplication logic."""

    def test_compute_observation_hash_consistent(self) -> None:
        """Test hash function produces consistent results."""
        hash1 = _compute_observation_hash("Test Title", "error", "Bash")
        hash2 = _compute_observation_hash("Test Title", "error", "Bash")
        assert hash1 == hash2
        assert len(hash1) == 16  # SHA256 truncated to 16 chars

    def test_compute_observation_hash_different_for_different_inputs(self) -> None:
        """Test hash function produces different results for different inputs."""
        hash1 = _compute_observation_hash("Title A", "error", "Bash")
        hash2 = _compute_observation_hash("Title B", "error", "Bash")
        hash3 = _compute_observation_hash("Title A", "decision", "Bash")
        hash4 = _compute_observation_hash("Title A", "error", "Read")

        assert hash1 != hash2
        assert hash1 != hash3
        assert hash1 != hash4

    def test_create_observation_skips_duplicate(self) -> None:
        """Test that duplicate observations in same session are skipped."""
        session_id = str(uuid.uuid4())

        # First observation should succeed
        result1 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Duplicate Test",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result1 is not None
        assert "id" in result1

        # Second identical observation should be skipped
        result2 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Duplicate Test",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result2 is None  # Duplicate was skipped

    def test_create_observation_allows_different_title(self) -> None:
        """Test that different titles create separate observations."""
        session_id = str(uuid.uuid4())

        result1 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Title One",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result1 is not None

        result2 = create_observation(
            project_id="summitflow",
            session_id=session_id,
            agent_type="test",
            observation_type="test_dedup",
            title="Title Two",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result2 is not None
        assert result1["id"] != result2["id"]

    def test_create_observation_allows_different_session(self) -> None:
        """Test that same observation in different sessions is allowed."""
        result1 = create_observation(
            project_id="summitflow",
            session_id=str(uuid.uuid4()),
            agent_type="test",
            observation_type="test_dedup",
            title="Same Title",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result1 is not None

        result2 = create_observation(
            project_id="summitflow",
            session_id=str(uuid.uuid4()),
            agent_type="test",
            observation_type="test_dedup",
            title="Same Title",
            tool_name="TestTool",
            skip_memory_check=True,
        )
        assert result2 is not None
        assert result1["id"] != result2["id"]
