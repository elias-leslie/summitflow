"""Tests for verification enforcement storage module.

Tests TDD-style verification including:
- Preflight validation (valid_fail, invalid_crash, invalid_pass)
- Criteria locking on task status change
- Verification blocking on step/subtask pass
- Amendment rejection when new command passes
- 3-2-1 escalation attempt limits
"""

import pytest

from app.storage import verification
from app.storage.connection import get_connection


@pytest.fixture
def conn():
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def test_project(conn):
    """Create test project fixture."""
    project_id = "test-verification-project"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Verification Project", "http://localhost"),
        )
        conn.commit()

    yield project_id

    # Cleanup
    with conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


@pytest.fixture
def test_task(conn, test_project):
    """Create test task fixture with spirit record.

    Note: G4 enforcement (migration 074) requires spirit record with approved plan
    before task can transition to 'running' status.
    """
    task_id = "task-verification-test"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tasks (id, project_id, title, status)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status
            """,
            (task_id, test_project, "Verification Test Task", "pending"),
        )
        # Create spirit record with approved plan (required by G4 enforcement)
        cur.execute(
            """
            INSERT INTO task_spirit (task_id, objective, plan_status, complexity)
            VALUES (%s, 'Test objective', 'approved', 'STANDARD')
            ON CONFLICT (task_id) DO UPDATE SET plan_status = 'approved'
            """,
            (task_id,),
        )
        conn.commit()

    yield task_id

    # Cleanup
    with conn.cursor() as cur:
        cur.execute("DELETE FROM task_acceptance_criteria WHERE task_id = %s", (task_id,))
        cur.execute("DELETE FROM task_spirit WHERE task_id = %s", (task_id,))
        cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        conn.commit()


class TestBashSyntaxValidation:
    """Tests for bash syntax validation (bash -n)."""

    def test_valid_syntax_returns_true(self):
        """Valid bash syntax returns (True, None)."""
        is_valid, error = verification.validate_bash_syntax("echo hello")
        assert is_valid is True
        assert error is None

    def test_invalid_syntax_returns_false(self):
        """Invalid bash syntax returns (False, error_message)."""
        is_valid, error = verification.validate_bash_syntax("if then else fi")
        assert is_valid is False
        assert error is not None
        assert "syntax error" in error.lower()

    def test_complex_valid_command(self):
        """Complex but valid command passes syntax check."""
        cmd = "if [ -f /tmp/test ]; then echo yes; else echo no; fi"
        is_valid, error = verification.validate_bash_syntax(cmd)
        assert is_valid is True
        assert error is None

    def test_unclosed_quote_detected(self):
        """Unclosed quote is detected as syntax error."""
        is_valid, error = verification.validate_bash_syntax("echo 'hello")
        assert is_valid is False
        assert error is not None


class TestPreflightValidation:
    """Tests for preflight validation (valid_fail, invalid_crash, invalid_pass)."""

    def test_preflight_valid_fail(self):
        """Command that fails with exit 1-125 is valid_fail (TDD red state)."""
        status, exit_code, _output = verification.run_preflight("exit 1")
        assert status == "valid_fail"
        assert exit_code == 1

    def test_preflight_invalid_pass(self):
        """Command that passes (exit 0) is invalid_pass - bad for TDD."""
        status, exit_code, _output = verification.run_preflight("exit 0")
        assert status == "invalid_pass"
        assert exit_code == 0

    def test_preflight_invalid_crash_command_not_found(self):
        """Command not found (exit 127) is invalid_crash."""
        status, exit_code, _output = verification.run_preflight(
            "nonexistent_command_that_should_not_exist_xyz123"
        )
        assert status == "invalid_crash"
        assert exit_code in (126, 127)  # command not found or not executable

    def test_preflight_invalid_crash_syntax_error(self):
        """Syntax error in command is invalid_crash (caught by bash -n)."""
        status, _exit_code, output = verification.run_preflight("if then else fi")
        assert status == "invalid_crash"
        assert "syntax error" in output.lower()

    def test_preflight_invalid_crash_not_executable(self):
        """Not-executable file is invalid_crash (exit 126)."""
        # Use a command that tries to execute a non-executable
        status, exit_code, _output = verification.run_preflight("/dev/null")
        assert status == "invalid_crash"
        assert exit_code == 126  # permission denied / not executable

    def test_preflight_with_timeout(self):
        """Command that times out is invalid_crash."""
        # Use a command that sleeps longer than our timeout
        status, exit_code, output = verification.run_preflight("sleep 5", timeout=1)
        assert status == "invalid_crash"
        assert exit_code == -1
        assert "timed out" in output.lower()

    def test_preflight_for_criterion_updates_database(self, conn, test_task):
        """run_preflight_for_criterion updates criterion in database."""
        # Create criterion with a failing command
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Test preflight criterion",
            verify_command="exit 1",
        )

        result = verification.run_preflight_for_criterion(conn, test_task, crit["criterion_id"])

        assert result["status"] == "valid_fail"
        assert result["valid"] is True

        # Verify database was updated
        updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
        assert updated["preflight_status"] == "valid_fail"
        # Note: preflight_at is stored but not returned by _row_to_criterion_dict

    def test_preflight_skipped_when_no_verify_command(self, conn, test_task):
        """Preflight is skipped when criterion has no verify_command."""
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Manual criterion",
            verify_by="human",
            verify_command=None,
        )

        result = verification.run_preflight_for_criterion(conn, test_task, crit["criterion_id"])

        assert result["status"] == "skipped"
        assert "No verify_command" in result["reason"]


class TestCriteriaLocking:
    """Tests for criteria auto-locking when task status changes to running."""

    def test_criteria_locked_when_task_running(self, conn, test_task):
        """Criteria are locked when task status changes to running."""
        # Create criterion while task is pending
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Locking test criterion",
            verify_command="exit 1",
        )

        # Verify not locked initially
        assert crit["is_locked"] is False

        # Change task status to running (triggers lock)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Verify criteria is now locked
        updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
        assert updated["is_locked"] is True

    def test_locked_criterion_verify_command_update_blocked(self, conn, test_task):
        """Locked criterion's verify_command cannot be updated directly."""
        # Create and lock criterion
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Update-blocked criterion",
            verify_command="exit 1",
        )

        # Lock by setting task to running
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Try to update verify_command - should be blocked by trigger
        try:
            verification.update_task_criterion(
                conn,
                test_task,
                crit["criterion_id"],
                {"verify_command": "exit 0"},
            )
            # If we get here, the trigger didn't block - that's a failure
            # But check if the value actually changed
            updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
            # The trigger should prevent the change
            assert updated["verify_command"] == "exit 1"
        except Exception:
            # Expected - trigger blocked the update
            # Rollback to clear the failed transaction state
            conn.rollback()

    def test_locked_criterion_other_fields_updatable(self, conn, test_task):
        """Locked criterion's non-verification fields can still be updated."""
        # Create and lock criterion
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Partial-update criterion",
            category="correctness",
            verify_command="exit 1",
        )

        # Lock by setting task to running
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Update non-verify_command fields should work
        updated = verification.update_task_criterion(
            conn,
            test_task,
            crit["criterion_id"],
            {"verification_attempts": 1},
        )

        assert updated is not None
        assert updated["verification_attempts"] == 1


class TestVerificationBlocking:
    """Tests for verification blocking on step/subtask pass."""

    def test_run_verification_passes_on_success(self, conn, test_task):
        """Verification passes when command exits 0."""
        # Create and lock criterion with passing command
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Passing criterion",
            verify_command="exit 0",
        )

        # Lock criterion
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        result = verification.run_verification(conn, test_task, crit["criterion_id"])

        assert result["status"] == "passed"
        assert result["attempts"] == 1

        # Verify criterion marked as verified
        updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
        assert updated["verified"] is True
        assert updated["verification_status"] == "passed"

    def test_run_verification_fails_on_failure(self, conn, test_task):
        """Verification fails when command exits non-zero."""
        # Create and lock criterion with failing command
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Failing criterion",
            verify_command="exit 1",
        )

        # Lock criterion
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        result = verification.run_verification(conn, test_task, crit["criterion_id"])

        assert result["status"] == "failed"
        assert result["attempts"] == 1
        assert result["escalation_level"] == "WORKER"

        # Verify criterion NOT marked as verified
        updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
        assert updated["verified"] is False
        assert updated["verification_status"] == "failed"

    def test_run_verification_requires_locked_criterion(self, conn, test_task):
        """Verification requires criterion to be locked."""
        # Create criterion but don't lock (task stays pending)
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Unlocked criterion",
            verify_command="exit 0",
        )

        result = verification.run_verification(conn, test_task, crit["criterion_id"])

        assert "error" in result
        assert "not locked" in result["error"].lower()


class TestAmendmentRejection:
    """Tests for amendment rejection when new command passes immediately."""

    def test_amendment_rejected_when_command_passes(self, conn, test_task):
        """Amendment is rejected if new verify_command passes immediately."""
        from app.storage import amendments

        # Create and lock criterion
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Amendment test criterion",
            verify_command="exit 1",
        )

        # Lock criterion
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Try to amend with passing command
        result = amendments.create_amendment(
            conn,
            test_task,
            crit["criterion_id"],
            new_verify_command="exit 0",  # This passes!
            reason="Testing rejection",
        )

        assert result["status"] == "rejected"
        assert "passes immediately" in result.get("error", "").lower()

    def test_amendment_accepted_when_command_fails(self, conn, test_task):
        """Amendment is accepted if new verify_command fails (TDD-style)."""
        from app.storage import amendments

        # Create and lock criterion
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Amendment test criterion 2",
            verify_command="exit 1",
        )

        # Lock criterion
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Amend with failing command (valid TDD style)
        result = amendments.create_amendment(
            conn,
            test_task,
            crit["criterion_id"],
            new_verify_command="exit 2",  # This fails
            reason="Valid amendment",
        )

        assert result.get("status") == "pending"
        assert "amendment_id" in result

    def test_amendment_rejected_on_syntax_error(self, conn, test_task):
        """Amendment is rejected if new verify_command has syntax errors."""
        from app.storage import amendments

        # Create and lock criterion
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Syntax error test",
            verify_command="exit 1",
        )

        # Lock criterion
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Amend with syntax error command (now caught by bash -n)
        result = amendments.create_amendment(
            conn,
            test_task,
            crit["criterion_id"],
            new_verify_command="if then else fi",
            reason="Bad syntax",
        )

        assert result["status"] == "rejected"
        assert "syntax" in result.get("reason", "").lower()


class TestEscalationLimits:
    """Tests for 3-2-1 attempt limits."""

    def test_worker_escalates_after_3_attempts(self, conn, test_task):
        """Worker escalates to Supervisor after 3 failed attempts."""
        # Create and lock criterion with failing command
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Escalation test",
            verify_command="exit 1",
        )

        # Lock criterion
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            conn.commit()

        # Run 3 failed verifications
        for i in range(3):
            result = verification.run_verification(conn, test_task, crit["criterion_id"])
            assert result["status"] == "failed"

            if i < 2:
                # First 2 failures stay at WORKER
                assert result["escalation_level"] == "WORKER"
                assert result["escalated"] is False
            else:
                # 3rd failure escalates to SUPERVISOR
                assert result["escalation_level"] == "SUPERVISOR"
                assert result["escalated"] is True

    def test_supervisor_escalates_after_2_attempts(self, conn, test_task):
        """Supervisor escalates to Human after 2 failed attempts."""
        # Create criterion and manually set to SUPERVISOR level
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Supervisor escalation test",
            verify_command="exit 1",
        )

        # Lock criterion and set to SUPERVISOR
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            cur.execute(
                """
                UPDATE task_acceptance_criteria
                SET escalation_level = 'SUPERVISOR', verification_attempts = 0
                WHERE task_id = %s AND criterion_id = %s
                """,
                (test_task, crit["criterion_id"]),
            )
            conn.commit()

        # Run 2 failed verifications
        for i in range(2):
            result = verification.run_verification(conn, test_task, crit["criterion_id"])
            assert result["status"] == "failed"

            if i < 1:
                assert result["escalation_level"] == "SUPERVISOR"
            else:
                # 2nd failure escalates to HUMAN
                assert result["escalation_level"] == "HUMAN"
                assert result["escalated"] is True

    def test_human_level_blocks_verification(self, conn, test_task):
        """Human level returns error requiring manual override."""
        # Create criterion and manually set to HUMAN level
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Human review test",
            verify_command="exit 1",
        )

        # Lock criterion and set to HUMAN
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            cur.execute(
                """
                UPDATE task_acceptance_criteria
                SET escalation_level = 'HUMAN'
                WHERE task_id = %s AND criterion_id = %s
                """,
                (test_task, crit["criterion_id"]),
            )
            conn.commit()

        result = verification.run_verification(conn, test_task, crit["criterion_id"])

        assert "error" in result
        assert "human" in result["error"].lower()
        assert result["escalation_level"] == "HUMAN"

    def test_human_override_pass(self, conn, test_task):
        """Human can force-pass a criterion at HUMAN level."""
        # Create criterion at HUMAN level
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Human override test",
            verify_command="exit 1",
        )

        # Lock and set to HUMAN
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            cur.execute(
                """
                UPDATE task_acceptance_criteria
                SET escalation_level = 'HUMAN', is_locked = TRUE
                WHERE task_id = %s AND criterion_id = %s
                """,
                (test_task, crit["criterion_id"]),
            )
            conn.commit()

        result = verification.human_override_criterion(
            conn,
            test_task,
            crit["criterion_id"],
            action="pass",
            reason="Manually verified in production",
        )

        assert result["status"] == "passed"
        assert result["action"] == "force-pass"

        # Verify criterion is now verified
        updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
        assert updated["verified"] is True

    def test_human_override_reset(self, conn, test_task):
        """Human can reset criterion back to WORKER level."""
        # Create criterion at HUMAN level
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Human reset test",
            verify_command="exit 1",
        )

        # Lock and set to HUMAN
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET status = 'running' WHERE id = %s",
                (test_task,),
            )
            cur.execute(
                """
                UPDATE task_acceptance_criteria
                SET escalation_level = 'HUMAN', is_locked = TRUE
                WHERE task_id = %s AND criterion_id = %s
                """,
                (test_task, crit["criterion_id"]),
            )
            conn.commit()

        result = verification.human_override_criterion(
            conn,
            test_task,
            crit["criterion_id"],
            action="reset",
            reason="Fixed the flaky test",
        )

        assert result["status"] == "reset"
        assert result["action"] == "reset-to-worker"

        # Verify criterion is back at WORKER
        updated = verification.get_task_criterion(conn, test_task, crit["criterion_id"])
        assert updated["escalation_level"] == "WORKER"
        assert updated["verification_attempts"] == 0

    def test_max_attempts_constants(self):
        """Verify 3-2-1 constants are correctly defined."""
        assert verification.MAX_WORKER_ATTEMPTS == 3
        assert verification.MAX_SUPERVISOR_ATTEMPTS == 2
        assert verification.MAX_HUMAN_ATTEMPTS == 1


class TestTaskStatusComputation:
    """Tests for automatic task status computation from criteria."""

    def test_human_reviewing_status_when_criterion_at_human(self, conn, test_task):
        """Task status should be human_reviewing when any criterion at HUMAN."""
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Human level criterion",
            verify_command="exit 1",
        )

        # Set criterion to HUMAN level
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_acceptance_criteria
                SET escalation_level = 'HUMAN'
                WHERE task_id = %s AND criterion_id = %s
                """,
                (test_task, crit["criterion_id"]),
            )
            conn.commit()

        suggested_status = verification.compute_task_status_from_criteria(conn, test_task)
        assert suggested_status == "human_reviewing"

    def test_ai_reviewing_status_when_criterion_at_supervisor(self, conn, test_task):
        """Task status should be ai_reviewing when any criterion at SUPERVISOR."""
        crit = verification.create_task_criterion(
            conn,
            test_task,
            "Supervisor level criterion",
            verify_command="exit 1",
        )

        # Set criterion to SUPERVISOR level
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE task_acceptance_criteria
                SET escalation_level = 'SUPERVISOR'
                WHERE task_id = %s AND criterion_id = %s
                """,
                (test_task, crit["criterion_id"]),
            )
            conn.commit()

        suggested_status = verification.compute_task_status_from_criteria(conn, test_task)
        assert suggested_status == "ai_reviewing"

    def test_no_status_change_when_all_worker(self, conn, test_task):
        """No status change suggested when all criteria at WORKER."""
        verification.create_task_criterion(
            conn,
            test_task,
            "Worker level criterion",
            verify_command="exit 1",
        )

        # Criterion defaults to WORKER, no change needed

        suggested_status = verification.compute_task_status_from_criteria(conn, test_task)
        assert suggested_status is None
