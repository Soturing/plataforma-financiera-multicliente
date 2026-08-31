from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.security.models import ModuleCode, RoleCode


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: RoleCode
    tenant_id: UUID | None = None
    modules: set[ModuleCode] = Field(default_factory=set, max_length=15)
    branch_ids: set[UUID] = Field(default_factory=set, max_length=500)
    conditional_permissions: set[str] = Field(default_factory=set, max_length=100)
    all_modules: bool = False
    all_branches: bool = False
    assignment_valid_until: datetime | None = None
    reason: str = Field(min_length=3, max_length=500)


class InvitationCreatedResponse(BaseModel):
    invitation_id: UUID
    invitation_token: str
    expires_at: datetime


class SuspendIdentityRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class RevokeSessionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class LifecycleActionResponse(BaseModel):
    status: str = "ok"
