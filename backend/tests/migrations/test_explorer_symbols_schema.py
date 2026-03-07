"""Tests verifying explorer symbol schema is present."""

from __future__ import annotations

from app.storage.connection import get_connection


class TestExplorerSymbolsTable:
    """Verify explorer_symbols table and key indexes exist."""

    def test_explorer_symbols_table_exists(self, db_schema_initialized: None) -> None:
        """explorer_symbols table should exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'explorer_symbols'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is True

    def test_explorer_symbols_has_project_fk(self, db_schema_initialized: None) -> None:
        """explorer_symbols should reference projects by project_id."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.table_name = 'explorer_symbols'
                      AND tc.constraint_type = 'FOREIGN KEY'
                      AND kcu.column_name = 'project_id'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is True

    def test_explorer_symbols_has_unique_project_symbol_id(self, db_schema_initialized: None) -> None:
        """explorer_symbols should enforce stable symbol ids per project."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'explorer_symbols'
                      AND indexdef LIKE '%(project_id, symbol_id)%'
                      AND indexdef LIKE 'CREATE UNIQUE INDEX%'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is True

    def test_explorer_symbols_has_file_lookup_index(self, db_schema_initialized: None) -> None:
        """explorer_symbols should support fast file-scoped refresh and lookup."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND tablename = 'explorer_symbols'
                      AND indexdef LIKE '%(project_id, file_path)%'
                )
                """
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] is True
