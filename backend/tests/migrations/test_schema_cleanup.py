"""Tests verifying schema cleanup migrations were applied.

ac-002: Legacy tables dropped, enforcement triggers removed, dead columns cleaned
"""

from __future__ import annotations

import pytest

from app.storage.connection import get_connection


class TestLegacyTablesDropped:
    """Verify legacy criteria tables have been dropped."""

    def test_acceptance_criteria_table_dropped(self) -> None:
        """acceptance_criteria table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'acceptance_criteria'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "acceptance_criteria table should be dropped"

    def test_task_criteria_table_dropped(self) -> None:
        """task_criteria table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'task_criteria'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "task_criteria table should be dropped"

    def test_capability_criteria_table_dropped(self) -> None:
        """capability_criteria table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'capability_criteria'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "capability_criteria table should be dropped"

    def test_criterion_amendments_table_dropped(self) -> None:
        """criterion_amendments table should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'criterion_amendments'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "criterion_amendments table should be dropped"


class TestEnforcementTriggersDropped:
    """Verify enforcement triggers have been dropped."""

    def test_lock_criteria_trigger_dropped(self) -> None:
        """lock_criteria_on_running trigger should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'lock_criteria_on_running'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "lock_criteria_on_running trigger should be dropped"

    def test_prevent_locked_changes_trigger_dropped(self) -> None:
        """prevent_locked_criteria_changes trigger should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'prevent_locked_criteria_changes'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "prevent_locked_criteria_changes trigger should be dropped"

    def test_verification_status_trigger_dropped(self) -> None:
        """enforce_verified_requires_verification_status trigger should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'enforce_verified_requires_verification_status'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, (
                "enforce_verified_requires_verification_status trigger should be dropped"
            )

    def test_criteria_qa_trigger_dropped(self) -> None:
        """enforce_criteria_verified_before_qa_pass trigger should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'enforce_criteria_verified_before_qa_pass'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "enforce_criteria_verified_before_qa_pass trigger should be dropped"

    def test_qa_signoff_trigger_dropped(self) -> None:
        """enforce_qa_signoff_before_complete trigger should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'enforce_qa_signoff_before_complete'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "enforce_qa_signoff_before_complete trigger should be dropped"

    def test_plan_approval_trigger_dropped(self) -> None:
        """enforce_plan_approval_before_running trigger should not exist."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'enforce_plan_approval_before_running'
                )
                """
            )
            exists = cur.fetchone()[0]
            assert not exists, "enforce_plan_approval_before_running trigger should be dropped"


class TestDeadColumnsDropped:
    """Verify dead columns have been removed from task_acceptance_criteria."""

    @pytest.fixture
    def tac_columns(self) -> list[str]:
        """Get current task_acceptance_criteria columns."""
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'task_acceptance_criteria'
                ORDER BY ordinal_position
                """
            )
            return [row[0] for row in cur.fetchall()]

    def test_is_locked_column_dropped(self, tac_columns: list[str]) -> None:
        """is_locked column should not exist."""
        assert "is_locked" not in tac_columns, "is_locked column should be dropped"

    def test_locked_at_column_dropped(self, tac_columns: list[str]) -> None:
        """locked_at column should not exist."""
        assert "locked_at" not in tac_columns, "locked_at column should be dropped"

    def test_preflight_columns_dropped(self, tac_columns: list[str]) -> None:
        """preflight_* columns should not exist."""
        preflight_cols = [c for c in tac_columns if c.startswith("preflight_")]
        assert not preflight_cols, f"preflight columns should be dropped: {preflight_cols}"

    def test_verification_columns_dropped(self, tac_columns: list[str]) -> None:
        """verification_* columns (except verify_*) should not exist."""
        verification_cols = [
            c for c in tac_columns if c.startswith("verification_") and not c.startswith("verify")
        ]
        assert not verification_cols, f"verification columns should be dropped: {verification_cols}"

    def test_escalation_level_column_dropped(self, tac_columns: list[str]) -> None:
        """escalation_level column should not exist."""
        assert "escalation_level" not in tac_columns, "escalation_level column should be dropped"

    def test_core_columns_remain(self, tac_columns: list[str]) -> None:
        """Core columns should still exist."""
        expected = [
            "id",
            "task_id",
            "criterion_id",
            "criterion",
            "verify_by",
            "verify_command",
            "verified",
        ]
        for col in expected:
            assert col in tac_columns, f"{col} column should still exist"
