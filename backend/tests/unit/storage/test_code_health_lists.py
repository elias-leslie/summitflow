"""Unit tests for code_health_lists storage layer."""

from unittest.mock import MagicMock, patch

from app.storage import code_health_lists


class TestCreateListEntry:
    """Test create_list_entry function."""

    @patch("app.storage.code_health_lists.get_connection")
    def test_creates_allow_list_entry(self, mock_get_conn: MagicMock) -> None:
        """Test creating an allow list entry."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            1,  # id
            "summitflow",  # project_id
            "allow",  # list_type
            "compat_comments",  # category
            "backward compatibility",  # pattern
            None,  # file_glob
            "Intentional compat",  # reason
            1.0,  # confidence
            "manual",  # source
            "test-user",  # created_by
            MagicMock(isoformat=lambda: "2026-01-03T12:00:00"),  # created_at
        )
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        result = code_health_lists.create_list_entry(
            project_id="summitflow",
            list_type="allow",
            category="compat_comments",
            pattern="backward compatibility",
            reason="Intentional compat",
            created_by="test-user",
        )

        assert result["id"] == 1
        assert result["list_type"] == "allow"
        assert result["category"] == "compat_comments"
        assert result["pattern"] == "backward compatibility"
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("app.storage.code_health_lists.get_connection")
    def test_creates_block_list_entry_with_file_glob(self, mock_get_conn: MagicMock) -> None:
        """Test creating a block list entry with file glob."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            2,
            "summitflow",
            "block",
            "legacy_vars",
            "old_config",
            "app/config/*.py",
            "Tech debt",
            0.9,
            "agent",
            "code-health-agent",
            MagicMock(isoformat=lambda: "2026-01-03T12:00:00"),
        )
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        result = code_health_lists.create_list_entry(
            project_id="summitflow",
            list_type="block",
            category="legacy_vars",
            pattern="old_config",
            file_glob="app/config/*.py",
            confidence=0.9,
            source="agent",
            created_by="code-health-agent",
        )

        assert result["id"] == 2
        assert result["list_type"] == "block"
        assert result["file_glob"] == "app/config/*.py"
        assert result["confidence"] == 0.9
        assert result["source"] == "agent"


class TestGetListEntries:
    """Test get_list_entries function."""

    @patch("app.storage.code_health_lists.get_connection")
    def test_gets_all_entries_for_project(self, mock_get_conn: MagicMock) -> None:
        """Test getting all entries for a project."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (
                1,
                "summitflow",
                "allow",
                "compat_comments",
                "test",
                None,
                None,
                1.0,
                "manual",
                None,
                MagicMock(isoformat=lambda: "2026-01-03T12:00:00"),
            ),
            (
                2,
                "summitflow",
                "block",
                "legacy_vars",
                "old_thing",
                None,
                None,
                0.8,
                "agent",
                None,
                MagicMock(isoformat=lambda: "2026-01-03T12:00:00"),
            ),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        result = code_health_lists.get_list_entries("summitflow")

        assert len(result) == 2
        assert result[0]["list_type"] == "allow"
        assert result[1]["list_type"] == "block"

    @patch("app.storage.code_health_lists.get_connection")
    def test_filters_by_list_type(self, mock_get_conn: MagicMock) -> None:
        """Test filtering by list_type."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (
                1,
                "summitflow",
                "allow",
                "compat_comments",
                "test",
                None,
                None,
                1.0,
                "manual",
                None,
                MagicMock(isoformat=lambda: "2026-01-03T12:00:00"),
            ),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        result = code_health_lists.get_list_entries("summitflow", list_type="allow")

        assert len(result) == 1
        assert result[0]["list_type"] == "allow"
        # Verify the query included list_type filter
        call_args = mock_cursor.execute.call_args
        assert "AND list_type = %s" in call_args[0][0]

    @patch("app.storage.code_health_lists.get_connection")
    def test_filters_by_category(self, mock_get_conn: MagicMock) -> None:
        """Test filtering by category."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        code_health_lists.get_list_entries("summitflow", category="legacy_vars")

        call_args = mock_cursor.execute.call_args
        assert "AND category = %s" in call_args[0][0]


class TestDeleteListEntry:
    """Test delete_list_entry function."""

    @patch("app.storage.code_health_lists.get_connection")
    def test_deletes_existing_entry(self, mock_get_conn: MagicMock) -> None:
        """Test deleting an existing entry."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        result = code_health_lists.delete_list_entry(1)

        assert result is True
        mock_conn.commit.assert_called_once()

    @patch("app.storage.code_health_lists.get_connection")
    def test_returns_false_for_nonexistent_entry(self, mock_get_conn: MagicMock) -> None:
        """Test returning False when entry doesn't exist."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=None)
        mock_get_conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_get_conn.return_value.__exit__ = MagicMock(return_value=None)

        result = code_health_lists.delete_list_entry(999)

        assert result is False


class TestIsPatternAllowed:
    """Test is_pattern_allowed function."""

    @patch("app.storage.code_health_lists.get_allow_list")
    def test_returns_true_when_pattern_in_allow_list(self, mock_get_allow_list: MagicMock) -> None:
        """Test returns True when pattern is in allow list."""
        mock_get_allow_list.return_value = [
            {
                "pattern": "backward compatibility",
                "file_glob": None,
            },
        ]

        result = code_health_lists.is_pattern_allowed(
            "summitflow", "compat_comments", "backward compatibility"
        )

        assert result is True

    @patch("app.storage.code_health_lists.get_allow_list")
    def test_returns_false_when_pattern_not_in_allow_list(
        self, mock_get_allow_list: MagicMock
    ) -> None:
        """Test returns False when pattern is not in allow list."""
        mock_get_allow_list.return_value = []

        result = code_health_lists.is_pattern_allowed(
            "summitflow", "compat_comments", "some other pattern"
        )

        assert result is False

    @patch("app.storage.code_health_lists.get_allow_list")
    def test_respects_file_glob_when_matching(self, mock_get_allow_list: MagicMock) -> None:
        """Test file glob is respected when checking patterns."""
        mock_get_allow_list.return_value = [
            {
                "pattern": "legacy_config",
                "file_glob": "app/config/*.py",
            },
        ]

        # Should match - file path matches glob
        result = code_health_lists.is_pattern_allowed(
            "summitflow",
            "legacy_vars",
            "legacy_config",
            file_path="app/config/settings.py",
        )
        assert result is True

        # Should not match - file path doesn't match glob
        result = code_health_lists.is_pattern_allowed(
            "summitflow",
            "legacy_vars",
            "legacy_config",
            file_path="app/api/routes.py",
        )
        assert result is False


class TestConvenienceFunctions:
    """Test convenience wrapper functions."""

    @patch("app.storage.code_health_lists.get_list_entries")
    def test_get_allow_list_calls_with_allow_type(self, mock_get_list: MagicMock) -> None:
        """Test get_allow_list calls get_list_entries with list_type='allow'."""
        mock_get_list.return_value = []

        code_health_lists.get_allow_list("summitflow", category="test")

        mock_get_list.assert_called_once_with("summitflow", list_type="allow", category="test")

    @patch("app.storage.code_health_lists.get_list_entries")
    def test_get_block_list_calls_with_block_type(self, mock_get_list: MagicMock) -> None:
        """Test get_block_list calls get_list_entries with list_type='block'."""
        mock_get_list.return_value = []

        code_health_lists.get_block_list("summitflow")

        mock_get_list.assert_called_once_with("summitflow", list_type="block", category=None)
