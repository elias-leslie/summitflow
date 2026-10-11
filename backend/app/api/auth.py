"""Current SummitFlow identity for the owner-only app."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..access_control import get_current_principal

router = APIRouter()


class MeResponse(BaseModel):
    authenticated: bool
    email: str | None
    role: str
    is_owner: bool
    is_local_bypass: bool = False


@router.get("/me", response_model=MeResponse)
def me(request: Request) -> MeResponse:
    """Return the current in-app identity."""
    principal = get_current_principal(request)
    if principal is None:
        return MeResponse(authenticated=False, email=None, role="none", is_owner=False)
    return MeResponse(
        authenticated=True,
        email=principal.email,
        role=principal.role,
        is_owner=principal.is_owner,
        is_local_bypass=principal.is_local_bypass,
    )
