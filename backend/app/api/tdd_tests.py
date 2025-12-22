"""Tests API - CRUD for TDD test registry."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..storage import tests as storage
from ..storage import test_runs as test_runs_storage

router = APIRouter()


class TestCreate(BaseModel):
    """Request model for creating a test."""

    test_id: str
    name: str
    test_type: str
    command: str | None = None
    script: str | None = None
    config: dict | None = None
    working_dir: str | None = None
    timeout_seconds: int = 60


class TestUpdate(BaseModel):
    """Request model for updating a test."""

    name: str | None = None
    test_type: str | None = None
    command: str | None = None
    script: str | None = None
    config: dict | None = None
    working_dir: str | None = None
    timeout_seconds: int | None = None


class TestResponse(BaseModel):
    """Response model for a test."""

    id: int
    project_id: str
    test_id: str
    name: str
    test_type: str
    command: str | None = None
    script: str | None = None
    config: dict = {}
    working_dir: str | None = None
    timeout_seconds: int
    last_run_at: str | None = None
    last_result: str | None = None
    last_duration_ms: int | None = None
    last_output: str | None = None
    last_error: str | None = None
    run_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    flaky_score: float = 0.0
    created_at: str | None = None
    updated_at: str | None = None


class TestWithHistoryResponse(TestResponse):
    """Response model for test with run history."""

    run_history: list[dict] = []
    linked_capabilities: list[dict] = []


@router.get("/{project_id}/tests", response_model=list[TestResponse])
async def list_tests(
    project_id: str,
    type: str | None = Query(None, description="Filter by test type"),
) -> list[TestResponse]:
    """List all tests for a project, optionally filtered by type."""
    tests_list = storage.list_tests(project_id, test_type=type)
    return [TestResponse(**t) for t in tests_list]


@router.get("/{project_id}/tests/{test_id}", response_model=TestWithHistoryResponse)
async def get_test(project_id: str, test_id: str) -> TestWithHistoryResponse:
    """Get a specific test with run history and linked capabilities."""
    test = storage.get_test(project_id, test_id)
    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    # Get run history
    run_history = test_runs_storage.get_test_runs(project_id, test_db_id=test["id"], limit=10)

    # Get linked capabilities
    linked_capabilities = storage.get_capabilities_for_test(project_id, test_id)

    return TestWithHistoryResponse(**test, run_history=run_history, linked_capabilities=linked_capabilities)


@router.post("/{project_id}/tests", response_model=TestResponse)
async def create_test(project_id: str, body: TestCreate) -> TestResponse:
    """Create a new test."""
    try:
        test = storage.create_test(
            project_id=project_id,
            test_id=body.test_id,
            name=body.name,
            test_type=body.test_type,
            command=body.command,
            script=body.script,
            config=body.config,
            working_dir=body.working_dir,
            timeout_seconds=body.timeout_seconds,
        )
        return TestResponse(**test)
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Test {body.test_id} already exists",
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{project_id}/tests/{test_id}", response_model=TestResponse)
async def update_test(project_id: str, test_id: str, body: TestUpdate) -> TestResponse:
    """Update a test."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    test = storage.update_test(project_id, test_id, **updates)
    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    return TestResponse(**test)


@router.delete("/{project_id}/tests/{test_id}")
async def delete_test(project_id: str, test_id: str) -> dict[str, str]:
    """Delete a test."""
    deleted = storage.delete_test(project_id, test_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    return {"status": "deleted", "test_id": test_id}


# ============================================================
# Test-Capability Linking
# ============================================================


class LinkTestRequest(BaseModel):
    """Request for linking test to capability."""

    is_primary: bool = False


@router.post("/{project_id}/tests/{test_id}/link/{capability_id}")
async def link_test_to_capability(
    project_id: str, test_id: str, capability_id: str, body: LinkTestRequest | None = None
) -> dict[str, str | bool]:
    """Link a test to a capability."""
    from ..storage import capabilities as cap_storage

    # Get test and capability db IDs
    test = storage.get_test(project_id, test_id)
    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    capability = cap_storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    is_primary = body.is_primary if body else False
    storage.link_test_to_capability(capability["id"], test["id"], is_primary)

    return {
        "status": "linked",
        "test_id": test_id,
        "capability_id": capability_id,
        "is_primary": is_primary,
    }


@router.delete("/{project_id}/tests/{test_id}/link/{capability_id}")
async def unlink_test_from_capability(
    project_id: str, test_id: str, capability_id: str
) -> dict[str, str]:
    """Unlink a test from a capability."""
    from ..storage import capabilities as cap_storage

    # Get test and capability db IDs
    test = storage.get_test(project_id, test_id)
    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    capability = cap_storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    unlinked = storage.unlink_test_from_capability(capability["id"], test["id"])
    if not unlinked:
        raise HTTPException(
            status_code=404,
            detail=f"Test {test_id} is not linked to capability {capability_id}",
        )

    return {"status": "unlinked", "test_id": test_id, "capability_id": capability_id}


# ============================================================
# Test Execution
# ============================================================


class TestRunRequest(BaseModel):
    """Request for running tests."""

    test_ids: list[str] | None = None
    tier: str | None = None  # smoke, unit, integration, full


class TestRunResult(BaseModel):
    """Result of a single test run."""

    test_id: str
    result: str  # passed, failed, error, timeout
    duration_ms: int
    output: str | None = None
    error: str | None = None


class TestRunResponse(BaseModel):
    """Response for test run."""

    test_id: str
    result: str
    duration_ms: int
    output: str | None = None
    error: str | None = None


@router.post("/{project_id}/tests/{test_id}/run", response_model=TestRunResponse)
async def run_single_test(project_id: str, test_id: str) -> TestRunResponse:
    """Run a single test and return the result.

    This endpoint executes the test and stores the result in test_runs table.
    """
    test = storage.get_test(project_id, test_id)
    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    # Import test runner service (lazy import to avoid circular deps)
    try:
        from ..services.test_runner import run_test
        result = await run_test(project_id, test_id)
        return TestRunResponse(**result)
    except ImportError:
        # Test runner not yet implemented - return stub
        raise HTTPException(
            status_code=501,
            detail="Test runner service not yet implemented (Phase 4)",
        )


@router.post("/{project_id}/tests/run", response_model=list[TestRunResult])
async def run_multiple_tests(project_id: str, body: TestRunRequest) -> list[TestRunResult]:
    """Run multiple tests and return results.

    If test_ids provided, run those specific tests.
    If tier provided, run all tests matching that tier.
    """
    # Import test runner service (lazy import to avoid circular deps)
    try:
        from ..services.test_runner import run_tests_batch
        results = await run_tests_batch(
            project_id,
            test_ids=body.test_ids,
            tier=body.tier,
        )
        return [TestRunResult(**r) for r in results]
    except ImportError:
        # Test runner not yet implemented - return stub
        raise HTTPException(
            status_code=501,
            detail="Test runner service not yet implemented (Phase 4)",
        )
