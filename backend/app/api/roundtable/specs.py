"""TDD spec generation and acceptance endpoints for roundtable."""

from typing import cast

from fastapi import APIRouter, HTTPException

from ...services.agents import AgentType
from ...services.roundtable import get_roundtable_service
from ...storage import roundtable as roundtable_storage
from .helpers import restore_session_from_db
from .models import (
    AcceptSpecRequest,
    AcceptSpecResponse,
    GenerateSpecRequest,
    GenerateSpecResponse,
    GetSpecResponse,
)

router = APIRouter()


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/generate-spec",
    response_model=GenerateSpecResponse,
)
async def generate_spec(
    project_id: str,
    session_id: str,
    request: GenerateSpecRequest,
):
    """Generate a TDD spec from the roundtable conversation.

    This extracts components, capabilities, and tests from the conversation
    and stores them in the session's generated_spec field for review.

    The spec is ephemeral until accepted - it can be regenerated multiple times
    as the conversation continues and requirements are refined.
    """
    service = get_roundtable_service()

    # Restore session from DB
    session = restore_session_from_db(service, session_id, project_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Extract spec
    spec = service.extract_spec_from_conversation(session, cast(AgentType, request.agent_type))

    # Count entities
    components_count = len(spec.get("components", []))
    capabilities_count = sum(len(c.get("capabilities", [])) for c in spec.get("components", []))
    tests_count = sum(
        len(cap.get("tests", []))
        for c in spec.get("components", [])
        for cap in c.get("capabilities", [])
    )

    return GenerateSpecResponse(
        session_id=session_id,
        spec=spec,
        components_count=components_count,
        capabilities_count=capabilities_count,
        tests_count=tests_count,
    )


@router.get(
    "/projects/{project_id}/roundtable/sessions/{session_id}/spec",
    response_model=GetSpecResponse,
)
async def get_spec(
    project_id: str,
    session_id: str,
):
    """Get the generated spec for a session.

    Returns the ephemeral spec that has been generated from the conversation.
    Returns null if no spec has been generated yet.
    """
    spec = roundtable_storage.get_generated_spec(session_id)
    return GetSpecResponse(session_id=session_id, spec=spec)


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/accept-spec",
    response_model=AcceptSpecResponse,
)
async def accept_spec(
    project_id: str,
    session_id: str,
    request: AcceptSpecRequest,
):
    """Accept the generated spec and create permanent entities.

    This converts the ephemeral generated_spec into permanent:
    - accepted_specs record (permanent spec record)
    - tdd_components
    - tdd_capabilities
    - tdd_tests (with test_capability_links)

    After acceptance, the generated_spec is cleared from the session.
    """
    service = get_roundtable_service()

    try:
        result = service.accept_spec(
            project_id=project_id,
            session_id=session_id,
            accepted_by=request.accepted_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return AcceptSpecResponse(
        spec_id=result["spec_id"],
        components_created=result["components_created"],
        capabilities_created=result["capabilities_created"],
        tests_created=result["tests_created"],
    )
