"""Tests verifying dead feature tables have been dropped.

ac-004: Evidence and Tests tables are dropped from database
"""

from __future__ import annotations

from app.storage.connection import get_connection


class TestEvidenceSystemDropped:
    """Verify Evidence system tables have been dropped (8 tables)."""

    def test_evidence_table_dropped(self) -> None:
        """evidence table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'evidence'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "evidence table should be dropped"

    def test_evidence_regressions_table_dropped(self) -> None:
        """evidence_regressions table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'evidence_regressions'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "evidence_regressions table should be dropped"

    def test_evidence_capture_jobs_table_dropped(self) -> None:
        """evidence_capture_jobs table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'evidence_capture_jobs'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "evidence_capture_jobs table should be dropped"

    def test_evidence_types_table_dropped(self) -> None:
        """evidence_types table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'evidence_types'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "evidence_types table should be dropped"

    def test_project_evidence_config_table_dropped(self) -> None:
        """project_evidence_config table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'project_evidence_config'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "project_evidence_config table should be dropped"

    def test_no_legacy_evidence_tables_exist(self) -> None:
        """Legacy evidence tables stay dropped even though route_evidence is allowed."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name LIKE '%evidence%'
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            legacy_tables = sorted(
                {
                    'evidence',
                    'evidence_regressions',
                    'evidence_capture_jobs',
                    'evidence_types',
                    'project_evidence_config',
                }.intersection(tables)
            )
            assert not legacy_tables, (
                f"Legacy evidence tables should not exist: {legacy_tables}"
            )


class TestTestsSystemDropped:
    """Verify Tests system tables have been dropped (3 tables)."""

    def test_tests_table_dropped(self) -> None:
        """tests table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'tests'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "tests table should be dropped"

    def test_test_runs_table_dropped(self) -> None:
        """test_runs table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'test_runs'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "test_runs table should be dropped"

    def test_criterion_tests_table_dropped(self) -> None:
        """criterion_tests table should not exist (linked to tests system)."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'criterion_tests'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            exists = row[0]
            assert not exists, "criterion_tests table should be dropped"
