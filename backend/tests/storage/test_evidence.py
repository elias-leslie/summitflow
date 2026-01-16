"""Tests for the evidence storage module."""

import pytest

from app.storage import evidence
from app.storage.connection import get_connection


@pytest.fixture
def conn():
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn):
    """Fixture to clean up test project data after tests."""
    project_id = "test-evidence-project"

    # Setup: ensure project exists
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Evidence Project", "http://localhost"),
        )
        conn.commit()

    yield project_id

    # Cleanup: remove test data
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM acceptance_criteria WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


@pytest.fixture
def test_explorer_entry(conn, cleanup_project):
    """Create a test explorer entry for linking evidence."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO explorer_entries (project_id, path, entry_type, name)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (cleanup_project, "/test/path", "file", "test"),
        )
        entry_id = cur.fetchone()[0]
        conn.commit()

    yield entry_id

    # Cleanup: delete evidence first (CHECK constraint requires task_id OR explorer_entry_id),
    # then delete the entry
    with conn.cursor() as cur:
        cur.execute("DELETE FROM evidence WHERE explorer_entry_id = %s", (entry_id,))
        cur.execute("DELETE FROM explorer_entries WHERE id = %s", (entry_id,))
        conn.commit()


class TestEvidenceCountForCriteria:
    """Tests for get_evidence_count_for_criteria."""

    def test_empty_criterion_ids_returns_empty(self, cleanup_project):
        """Empty list returns empty dict."""
        result = evidence.get_evidence_count_for_criteria(cleanup_project, [])
        assert result == {}

    def test_no_evidence_returns_empty(self, conn, cleanup_project):
        """Returns empty dict when no evidence exists for criteria."""
        # Create a criterion
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO acceptance_criteria (project_id, criterion_id, criterion, category, measurement)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (cleanup_project, "ac-001", "Test criterion", "correctness", "test"),
            )
            crit_id = cur.fetchone()[0]
            conn.commit()

        result = evidence.get_evidence_count_for_criteria(cleanup_project, [crit_id])
        assert result == {}

    def test_counts_evidence_per_criterion(self, conn, cleanup_project, test_explorer_entry):
        """Returns correct counts per criterion."""
        # Create two criteria
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO acceptance_criteria (project_id, criterion_id, criterion, category, measurement)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (cleanup_project, "ac-001", "Criterion 1", "correctness", "test"),
            )
            crit1_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO acceptance_criteria (project_id, criterion_id, criterion, category, measurement)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (cleanup_project, "ac-002", "Criterion 2", "correctness", "test"),
            )
            crit2_id = cur.fetchone()[0]

            # Add 2 evidence for crit1 (linked via explorer_entry_id)
            for i in range(2):
                cur.execute(
                    """
                    INSERT INTO evidence (
                        project_id, evidence_id, explorer_entry_id, evidence_type,
                        file_path, version, is_current, criterion_db_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                    """,
                    (
                        cleanup_project,
                        f"ev-{i}",
                        test_explorer_entry,
                        "screenshot",
                        f"/path/ev-{i}.png",
                        i + 1,
                        crit1_id,
                    ),
                )

            # Add 3 evidence for crit2
            for i in range(3):
                cur.execute(
                    """
                    INSERT INTO evidence (
                        project_id, evidence_id, explorer_entry_id, evidence_type,
                        file_path, version, is_current, criterion_db_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                    """,
                    (
                        cleanup_project,
                        f"ev-c2-{i}",
                        test_explorer_entry,
                        "screenshot",
                        f"/path/ev-c2-{i}.png",
                        i + 1,
                        crit2_id,
                    ),
                )

            conn.commit()

        result = evidence.get_evidence_count_for_criteria(cleanup_project, [crit1_id, crit2_id])
        assert result[crit1_id] == 2
        assert result[crit2_id] == 3

    def test_only_counts_current_versions(self, conn, cleanup_project, test_explorer_entry):
        """Only counts is_current=TRUE evidence."""
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO acceptance_criteria (project_id, criterion_id, criterion, category, measurement)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (cleanup_project, "ac-001", "Test criterion", "correctness", "test"),
            )
            crit_id = cur.fetchone()[0]

            # Add 1 current and 2 non-current
            cur.execute(
                """
                INSERT INTO evidence (
                    project_id, evidence_id, explorer_entry_id, evidence_type,
                    file_path, version, is_current, criterion_db_id
                ) VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                """,
                (
                    cleanup_project,
                    "ev-current",
                    test_explorer_entry,
                    "screenshot",
                    "/path/current.png",
                    3,
                    crit_id,
                ),
            )
            for i in range(2):
                cur.execute(
                    """
                    INSERT INTO evidence (
                        project_id, evidence_id, explorer_entry_id, evidence_type,
                        file_path, version, is_current, criterion_db_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, FALSE, %s)
                    """,
                    (
                        cleanup_project,
                        f"ev-old-{i}",
                        test_explorer_entry,
                        "screenshot",
                        f"/path/old-{i}.png",
                        i + 1,
                        crit_id,
                    ),
                )

            conn.commit()

        result = evidence.get_evidence_count_for_criteria(cleanup_project, [crit_id])
        assert result[crit_id] == 1  # Only the current one
