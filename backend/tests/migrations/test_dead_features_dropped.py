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
            exists = cur.fetchone()[0]
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
            exists = cur.fetchone()[0]
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
            exists = cur.fetchone()[0]
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
            exists = cur.fetchone()[0]
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
            exists = cur.fetchone()[0]
            assert not exists, "project_evidence_config table should be dropped"

    def test_no_evidence_tables_exist(self) -> None:
        """No tables with 'evidence' in name should exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name LIKE '%evidence%'
                """
            )
            tables = [row[0] for row in cur.fetchall()]
            assert not tables, f"Evidence tables should not exist: {tables}"


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
            exists = cur.fetchone()[0]
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
            exists = cur.fetchone()[0]
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
            exists = cur.fetchone()[0]
            assert not exists, "criterion_tests table should be dropped"
