"""Unit tests for memory_embeddings storage module."""

from unittest.mock import MagicMock, patch


class TestFindSimilarPatterns:
    """Tests for find_similar_patterns function."""

    @patch("app.storage.memory_embeddings.get_connection")
    def test_returns_empty_when_no_embedding(self, mock_get_conn):
        """Returns empty list when source pattern has no embedding."""
        from app.storage.memory_embeddings import find_similar_patterns

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (None,)  # No embedding
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = find_similar_patterns("test-pattern-id")

        assert result == []

    @patch("app.storage.memory_embeddings.get_connection")
    def test_returns_similar_patterns(self, mock_get_conn):
        """Returns patterns with similarity >= threshold."""
        from app.storage.memory_embeddings import find_similar_patterns

        mock_cursor = MagicMock()
        # First call returns embedding for source
        # Second call returns similar patterns
        mock_embedding = [0.1] * 768
        mock_cursor.fetchone.return_value = (mock_embedding,)
        mock_cursor.fetchall.return_value = [
            ("similar-id-1", 0.92),
            ("similar-id-2", 0.87),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = find_similar_patterns("source-id", min_similarity=0.85)

        assert len(result) == 2
        assert result[0]["pattern_id"] == "similar-id-1"
        assert result[0]["similarity_score"] == 0.92
        assert result[1]["pattern_id"] == "similar-id-2"
        assert result[1]["similarity_score"] == 0.87

    @patch("app.storage.memory_embeddings.get_connection")
    def test_filters_by_project(self, mock_get_conn):
        """Includes project filter when project_id provided."""
        from app.storage.memory_embeddings import find_similar_patterns

        mock_cursor = MagicMock()
        mock_embedding = [0.1] * 768
        mock_cursor.fetchone.return_value = (mock_embedding,)
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        find_similar_patterns("source-id", project_id="test-project")

        # Verify the execute call includes project_id
        call_args = mock_cursor.execute.call_args_list[1]
        query = call_args[0][0]
        params = call_args[0][1]
        assert "project_id = %s" in query
        assert "test-project" in params


class TestGetPatternsWithoutEmbeddings:
    """Tests for get_patterns_without_embeddings function."""

    @patch("app.storage.memory_embeddings.get_connection")
    def test_returns_patterns_needing_embeddings(self, mock_get_conn):
        """Returns patterns that lack embeddings."""
        from app.storage.memory_embeddings import get_patterns_without_embeddings

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("pat-1", "project-a", "Title 1", "Content 1"),
            ("pat-2", "project-a", "Title 2", "Content 2"),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        result = get_patterns_without_embeddings()

        assert len(result) == 2
        assert result[0]["id"] == "pat-1"
        assert result[0]["title"] == "Title 1"
        assert result[0]["content"] == "Content 1"

    @patch("app.storage.memory_embeddings.get_connection")
    def test_filters_by_project(self, mock_get_conn):
        """Filters by project_id when provided."""
        from app.storage.memory_embeddings import get_patterns_without_embeddings

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        get_patterns_without_embeddings(project_id="test-project", limit=50)

        call_args = mock_cursor.execute.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        assert "project_id = %s" in query
        assert params == ("test-project", 50)


class TestUpdatePatternEmbedding:
    """Tests for update_pattern_embedding function."""

    @patch("app.storage.memory_embeddings.get_connection")
    def test_updates_embedding(self, mock_get_conn):
        """Successfully updates pattern embedding."""
        from app.storage.memory_embeddings import update_pattern_embedding

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        embedding = [0.1] * 768
        result = update_pattern_embedding("pattern-id", embedding)

        assert result is True
        mock_conn.commit.assert_called_once()

    @patch("app.storage.memory_embeddings.get_connection")
    def test_returns_false_when_not_found(self, mock_get_conn):
        """Returns False when pattern not found."""
        from app.storage.memory_embeddings import update_pattern_embedding

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 0
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_get_conn.return_value.__enter__.return_value = mock_conn

        embedding = [0.1] * 768
        result = update_pattern_embedding("nonexistent", embedding)

        assert result is False
