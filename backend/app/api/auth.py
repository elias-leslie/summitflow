"""Identity and sharing management APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator

from ..access_control import (
    AccessPrincipal,
    get_current_principal,
    principal_grants,
    require_owner,
)
from ..storage import access as access_store

router = APIRouter()
RequireOwner = Depends(require_owner)

UserRole = Literal["owner", "viewer"]
ShareSection = Literal["design"]


class GrantResponse(BaseModel):
    project_id: str
    section: ShareSection
    created_at: datetime | None = None


class MeResponse(BaseModel):
    authenticated: bool
    email: str | None
    role: str
    is_owner: bool
    is_viewer: bool
    is_local_bypass: bool = False
    grants: list[GrantResponse] = Field(default_factory=list)


class ShareUserResponse(BaseModel):
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
    grants: list[GrantResponse] = Field(default_factory=list)


class UpsertShareUserRequest(BaseModel):
    email: str
    role: UserRole = "viewer"
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = access_store.normalize_email(value)
        if "@" not in email:
            raise ValueError("email must be an email address")
        return email


class SetProjectGrantsRequest(BaseModel):
    project_id: str
    sections: list[ShareSection] = Field(default_factory=list)


def _grant_response(grant: access_store.AccessGrant) -> GrantResponse:
    return GrantResponse(
        project_id=grant.project_id,
        section="design",
        created_at=grant.created_at,
    )


def _user_response(user: access_store.AccessUser) -> ShareUserResponse:
    return ShareUserResponse(
        email=user.email,
        role=user.role,  # type: ignore[arg-type]
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        grants=[_grant_response(grant) for grant in access_store.list_user_grants(user.email)],
    )


def _principal_grant_response(grant: dict[str, str]) -> GrantResponse:
    return GrantResponse(project_id=grant["project_id"], section="design")


@router.get("/me", response_model=MeResponse)
def me(request: Request) -> MeResponse:
    """Return current in-app identity and grants."""
    principal = get_current_principal(request)
    if principal is None:
        return MeResponse(
            authenticated=False,
            email=None,
            role="none",
            is_owner=False,
            is_viewer=False,
            grants=[],
        )
    return MeResponse(
        authenticated=True,
        email=principal.email,
        role=principal.role,
        is_owner=principal.is_owner,
        is_viewer=principal.is_viewer,
        is_local_bypass=principal.is_local_bypass,
        grants=[_principal_grant_response(grant) for grant in principal_grants(principal)],
    )


@router.get("/users", response_model=list[ShareUserResponse])
def list_share_users(
    _principal: AccessPrincipal = RequireOwner,
) -> list[ShareUserResponse]:
    """List DB-managed SummitFlow users and grants."""
    return [_user_response(user) for user in access_store.list_users()]


@router.post("/users", response_model=ShareUserResponse)
def upsert_share_user(
    request: UpsertShareUserRequest,
    _principal: AccessPrincipal = RequireOwner,
) -> ShareUserResponse:
    """Create or update a SummitFlow user."""
    user = access_store.upsert_user(
        request.email,
        request.role,
        is_active=request.is_active,
    )
    return _user_response(user)


@router.delete("/users/{email}", response_model=dict[str, str])
def delete_share_user(
    email: str,
    _principal: AccessPrincipal = RequireOwner,
) -> dict[str, str]:
    """Delete a SummitFlow user."""
    normalized = access_store.normalize_email(email)
    access_store.delete_user(normalized)
    return {"status": "deleted", "email": normalized}


@router.put("/users/{email}/grants", response_model=list[GrantResponse])
def set_share_user_grants(
    email: str,
    request: SetProjectGrantsRequest,
    _principal: AccessPrincipal = RequireOwner,
) -> list[GrantResponse]:
    """Replace one user's grants for one project."""
    grants = access_store.set_project_grants(
        email,
        request.project_id,
        list(request.sections),
    )
    return [_grant_response(grant) for grant in grants]
