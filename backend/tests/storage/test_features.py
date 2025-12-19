"""Unit tests for features storage layer with criteria support."""

import pytest

from app.storage import features as feat_store
from app.storage.connection import get_connection


@pytest.fixture
def test_feature():
    """Create and cleanup a test feature."""
    project_id = "summitflow"
    feature_id = "TEST-UNIT"

    # Ensure project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, "SummitFlow", "http://localhost:3001"),
        )
        conn.commit()

    # Create test feature
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO feature_capabilities (project_id, feature_id, name, category, acceptance_criteria)
            VALUES (%s, %s, %s, %s, '[]'::jsonb)
            ON CONFLICT (project_id, feature_id) DO UPDATE
            SET acceptance_criteria = '[]'::jsonb
            RETURNING id
            """,
            (project_id, feature_id, "Unit Test Feature", "Testing"),
        )
        conn.commit()

    yield {"project_id": project_id, "feature_id": feature_id}

    # Cleanup
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM feature_capabilities WHERE project_id = %s AND feature_id = %s",
            (project_id, feature_id),
        )
        conn.commit()


class TestAddCriterion:
    """Tests for add_criterion function."""

    def test_add_criterion_creates_with_passes_false(self, test_feature):
        """Test that add_criterion creates criterion with passes=false."""
        result = feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-001", "description": "Test criterion"},
        )

        assert result is not None
        assert result["id"] == "ac-001"
        assert result["passes"] is False
        assert result["description"] == "Test criterion"

    def test_add_criterion_with_all_fields(self, test_feature):
        """Test adding criterion with all optional fields."""
        result = feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {
                "id": "ac-002",
                "description": "Full criterion",
                "verification": "curl http://example.com",
                "type": "api",
            },
        )

        assert result["id"] == "ac-002"
        assert result["verification"] == "curl http://example.com"
        assert result["type"] == "api"
        assert result["passes"] is False

    def test_add_criterion_duplicate_raises_error(self, test_feature):
        """Test that adding duplicate criterion ID raises ValueError."""
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-dup", "description": "First"},
        )

        with pytest.raises(ValueError, match="already exists"):
            feat_store.add_criterion(
                test_feature["project_id"],
                test_feature["feature_id"],
                {"id": "ac-dup", "description": "Second"},
            )

    def test_add_criterion_nonexistent_feature_returns_none(self):
        """Test that adding to nonexistent feature returns None."""
        result = feat_store.add_criterion(
            "summitflow",
            "NONEXISTENT",
            {"id": "ac-001", "description": "Test"},
        )
        assert result is None


class TestUpdateCriterionStatus:
    """Tests for update_criterion_status function."""

    def test_update_criterion_status_changes_passes(self, test_feature):
        """Test that update_criterion_status changes passes field."""
        # Add criterion first
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-update", "description": "To update"},
        )

        # Update to passes=True
        result = feat_store.update_criterion_status(
            test_feature["project_id"],
            test_feature["feature_id"],
            "ac-update",
            True,
        )

        assert result is not None
        assert result["passes"] is True
        assert result["verified_at"] is not None

    def test_update_criterion_status_with_evidence(self, test_feature):
        """Test updating criterion with evidence ID."""
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-evidence", "description": "With evidence"},
        )

        result = feat_store.update_criterion_status(
            test_feature["project_id"],
            test_feature["feature_id"],
            "ac-evidence",
            True,
            evidence_id="ev-001",
        )

        assert result["evidence_id"] == "ev-001"

    def test_update_criterion_status_nonexistent_returns_none(self, test_feature):
        """Test updating nonexistent criterion returns None."""
        result = feat_store.update_criterion_status(
            test_feature["project_id"],
            test_feature["feature_id"],
            "nonexistent",
            True,
        )
        assert result is None


class TestGetCriteria:
    """Tests for get_criteria function."""

    def test_get_criteria_returns_all(self, test_feature):
        """Test that get_criteria returns all criteria for feature."""
        # Add multiple criteria
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-1", "description": "First"},
        )
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-2", "description": "Second"},
        )
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-3", "description": "Third"},
        )

        criteria = feat_store.get_criteria(
            test_feature["project_id"],
            test_feature["feature_id"],
        )

        assert len(criteria) == 3
        ids = [c["id"] for c in criteria]
        assert "ac-1" in ids
        assert "ac-2" in ids
        assert "ac-3" in ids

    def test_get_criteria_empty_feature(self, test_feature):
        """Test get_criteria on feature with no criteria."""
        criteria = feat_store.get_criteria(
            test_feature["project_id"],
            test_feature["feature_id"],
        )
        assert criteria == []

    def test_get_criteria_nonexistent_feature(self):
        """Test get_criteria on nonexistent feature returns empty list."""
        criteria = feat_store.get_criteria("summitflow", "NONEXISTENT")
        assert criteria == []


class TestCriteriaPersistence:
    """Tests for criteria persistence across queries."""

    def test_criteria_persists_across_queries(self, test_feature):
        """Test that criteria persists after adding and updating."""
        # Add criterion
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-persist", "description": "Persistent"},
        )

        # Update it
        feat_store.update_criterion_status(
            test_feature["project_id"],
            test_feature["feature_id"],
            "ac-persist",
            True,
        )

        # Query again and verify
        criteria = feat_store.get_criteria(
            test_feature["project_id"],
            test_feature["feature_id"],
        )

        assert len(criteria) == 1
        assert criteria[0]["id"] == "ac-persist"
        assert criteria[0]["passes"] is True
        assert criteria[0]["verified_at"] is not None

    def test_multiple_updates_persist(self, test_feature):
        """Test multiple status updates persist correctly."""
        feat_store.add_criterion(
            test_feature["project_id"],
            test_feature["feature_id"],
            {"id": "ac-multi", "description": "Multi-update"},
        )

        # Update to True
        feat_store.update_criterion_status(
            test_feature["project_id"],
            test_feature["feature_id"],
            "ac-multi",
            True,
        )

        # Update back to False
        feat_store.update_criterion_status(
            test_feature["project_id"],
            test_feature["feature_id"],
            "ac-multi",
            False,
        )

        criteria = feat_store.get_criteria(
            test_feature["project_id"],
            test_feature["feature_id"],
        )

        assert criteria[0]["passes"] is False
