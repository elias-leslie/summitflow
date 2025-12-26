"""Integration tests for capability status flow on test pass/fail.

Tests the TDD loop: when tests pass/fail, capability status updates automatically.
"""

import pytest
from app.storage import capabilities as cap_store
from app.storage import components as comp_store
from app.storage import test_runs as runs_store
from app.storage import tests as test_store
from app.storage.connection import get_connection


@pytest.fixture
def project_id():
    """Ensure test project exists."""
    project_id = "summitflow"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, "SummitFlow", "http://localhost:3001"),
        )
        conn.commit()
    return project_id


@pytest.fixture
def component(project_id):
    """Create and cleanup a test component."""
    comp = comp_store.create_component(
        project_id=project_id,
        component_id="test-comp-status-flow",
        name="Test Component for Status Flow",
    )
    yield comp
    comp_store.delete_component(project_id, "test-comp-status-flow")


@pytest.fixture
def capability(project_id, component):
    """Create and cleanup a test capability."""
    cap = cap_store.create_capability(
        project_id=project_id,
        component_id=component["id"],
        capability_id="test-cap-status-flow",
        name="Test Capability for Status Flow",
    )
    yield cap
    cap_store.delete_capability(project_id, "test-cap-status-flow")


@pytest.fixture
def test1(project_id):
    """Create and cleanup first test."""
    test = test_store.create_test(
        project_id=project_id,
        test_id="test-status-flow-1",
        name="Test 1 for Status Flow",
        test_type="pytest",
        command="pytest tests/unit/test1.py",
    )
    yield test
    test_store.delete_test(project_id, "test-status-flow-1")


@pytest.fixture
def test2(project_id):
    """Create and cleanup second test."""
    test = test_store.create_test(
        project_id=project_id,
        test_id="test-status-flow-2",
        name="Test 2 for Status Flow",
        test_type="pytest",
        command="pytest tests/unit/test2.py",
    )
    yield test
    test_store.delete_test(project_id, "test-status-flow-2")


class TestCapabilityStatusFlow:
    """Tests for capability status updates on test pass/fail."""

    def test_single_test_pass_updates_capability(self, project_id, capability, test1):
        """When the only linked test passes, capability goes to tests_passing."""
        # Link test to capability
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test1["id"],
        )

        # Verify initial status is pending
        cap = cap_store.get_capability(project_id, "test-cap-status-flow")
        assert cap["status"] == "pending"

        # Create a passing test run
        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test1["id"],
            run_type="manual",
            result="passed",
            duration_ms=100,
        )

        # Verify capability status is now tests_passing
        cap = cap_store.get_capability(project_id, "test-cap-status-flow")
        assert cap["status"] == "tests_passing"

    def test_partial_pass_keeps_pending(self, project_id, capability, test1, test2):
        """With 2 tests, passing 1 keeps capability pending."""
        # Link both tests to capability
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test1["id"],
        )
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test2["id"],
        )

        # Run test1 (pass)
        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test1["id"],
            run_type="manual",
            result="passed",
            duration_ms=100,
        )

        # Capability should still be pending (test2 not run/passed)
        cap = cap_store.get_capability(project_id, "test-cap-status-flow")
        assert cap["status"] == "pending"

    def test_all_pass_updates_to_tests_passing(self, project_id, capability, test1, test2):
        """With 2 tests, both passing sets capability to tests_passing."""
        # Link both tests to capability
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test1["id"],
        )
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test2["id"],
        )

        # Run test1 (pass) - need to update last_result for test1
        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test1["id"],
            run_type="manual",
            result="passed",
            duration_ms=100,
        )
        # Simulate that test1's last_result is now passed
        test_store.update_test_result(
            project_id=project_id,
            test_id="test-status-flow-1",
            result="passed",
            duration_ms=100,
        )

        # Run test2 (pass)
        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test2["id"],
            run_type="manual",
            result="passed",
            duration_ms=100,
        )

        # Capability should now be tests_passing
        cap = cap_store.get_capability(project_id, "test-cap-status-flow")
        assert cap["status"] == "tests_passing"

    def test_fail_resets_to_pending(self, project_id, capability, test1, test2):
        """After all tests pass, a failure resets capability to pending."""
        # Link both tests to capability
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test1["id"],
        )
        test_store.link_test_to_capability(
            capability_db_id=capability["id"],
            test_db_id=test2["id"],
        )

        # Both tests pass
        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test1["id"],
            run_type="manual",
            result="passed",
            duration_ms=100,
        )
        test_store.update_test_result(
            project_id=project_id,
            test_id="test-status-flow-1",
            result="passed",
            duration_ms=100,
        )

        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test2["id"],
            run_type="manual",
            result="passed",
            duration_ms=100,
        )
        test_store.update_test_result(
            project_id=project_id,
            test_id="test-status-flow-2",
            result="passed",
            duration_ms=100,
        )

        # Verify tests_passing
        cap = cap_store.get_capability(project_id, "test-cap-status-flow")
        assert cap["status"] == "tests_passing"

        # Now test1 fails
        runs_store.create_test_run(
            project_id=project_id,
            test_db_id=test1["id"],
            run_type="manual",
            result="failed",
            duration_ms=100,
        )

        # Capability should be back to pending
        cap = cap_store.get_capability(project_id, "test-cap-status-flow")
        assert cap["status"] == "pending"
