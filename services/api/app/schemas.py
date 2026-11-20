"""Request/response schemas for the control-plane API."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from harness_common import limits as L


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=512)


class TenantBrief(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    role: str = ""  # membership role of the current user in this tenant


class TenantOut(TenantBrief):
    status: str = "active"
    max_running: int = 4
    max_workspaces: int = 16
    daily_token_budget: int = 1_000_000
    cpu_per_space: int = L.DEFAULT_CPU_PER_SPACE
    memory_per_space_bytes: int = L.DEFAULT_MEMORY_PER_SPACE
    pids_per_space: int = L.DEFAULT_PIDS_PER_SPACE
    max_total_cpu: int = L.DEFAULT_MAX_TOTAL_CPU
    max_total_memory_bytes: int = L.DEFAULT_MAX_TOTAL_MEMORY
    max_total_pids: int = L.DEFAULT_MAX_TOTAL_PIDS


class UserBrief(BaseModel):
    id: uuid.UUID
    login_norm: str
    display_name: str
    is_platform_admin: bool


class LoginOut(BaseModel):
    user: UserBrief
    tenants: list[TenantBrief]
    active_tenant_id: uuid.UUID | None
    csrf_token: str


class MeOut(BaseModel):
    user: UserBrief
    tenants: list[TenantBrief]
    active_tenant_id: uuid.UUID | None
    csrf_token: str


class ActiveTenantIn(BaseModel):
    tenant_id: uuid.UUID


class _TenantResourceFields(BaseModel):
    cpu_per_space: int = Field(default=L.DEFAULT_CPU_PER_SPACE, ge=L.MIN_CPU, le=L.MAX_CPU_PER_SPACE)
    memory_per_space_bytes: int = Field(default=L.DEFAULT_MEMORY_PER_SPACE,
                                        ge=L.MIN_MEMORY_BYTES, le=L.MAX_MEMORY_PER_SPACE)
    pids_per_space: int = Field(default=L.DEFAULT_PIDS_PER_SPACE, ge=L.MIN_PIDS, le=L.MAX_PIDS_PER_SPACE)
    max_total_cpu: int = Field(default=L.DEFAULT_MAX_TOTAL_CPU, ge=1, le=L.MAX_TOTAL_CPU)
    max_total_memory_bytes: int = Field(default=L.DEFAULT_MAX_TOTAL_MEMORY, ge=1, le=L.MAX_TOTAL_MEMORY_BYTES)
    max_total_pids: int = Field(default=L.DEFAULT_MAX_TOTAL_PIDS, ge=1, le=L.MAX_TOTAL_PIDS)


class CreateTenantIn(_TenantResourceFields):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=255)
    max_running: int = Field(default=4, ge=0, le=1000)
    max_workspaces: int = Field(default=16, ge=0, le=10000)
    daily_token_budget: int = Field(default=1_000_000, ge=0)


class PatchTenantIn(BaseModel):
    name: str | None = None
    status: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    max_running: int | None = Field(default=None, ge=0, le=1000)
    max_workspaces: int | None = Field(default=None, ge=0, le=10000)
    daily_token_budget: int | None = Field(default=None, ge=0)
    cpu_per_space: int | None = Field(default=None, ge=L.MIN_CPU, le=L.MAX_CPU_PER_SPACE)
    memory_per_space_bytes: int | None = Field(default=None, ge=L.MIN_MEMORY_BYTES, le=L.MAX_MEMORY_PER_SPACE)
    pids_per_space: int | None = Field(default=None, ge=L.MIN_PIDS, le=L.MAX_PIDS_PER_SPACE)
    max_total_cpu: int | None = Field(default=None, ge=1, le=L.MAX_TOTAL_CPU)
    max_total_memory_bytes: int | None = Field(default=None, ge=1, le=L.MAX_TOTAL_MEMORY_BYTES)
    max_total_pids: int | None = Field(default=None, ge=1, le=L.MAX_TOTAL_PIDS)


class CreateUserIn(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=12, max_length=512)
    is_platform_admin: bool = False


class SetMemberIn(BaseModel):
    role: str = Field(pattern=r"^(tenant_admin|member)$")
    status: str = Field(default="active", pattern=r"^(active|disabled)$")


class CreateWorkspaceIn(BaseModel):
    owner_id: uuid.UUID
    template_version: str = Field(min_length=1, max_length=128)
    cpu: int | None = Field(default=None, ge=L.MIN_CPU, le=L.MAX_CPU_PER_SPACE)
    memory_bytes: int | None = Field(default=None, ge=L.MIN_MEMORY_BYTES, le=L.MAX_MEMORY_PER_SPACE)
    pids_limit: int | None = Field(default=None, ge=L.MIN_PIDS, le=L.MAX_PIDS_PER_SPACE)


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    owner_id: uuid.UUID
    template_version: str
    enabled: bool
    desired_state: str
    observed_state: str
    generation: int
    auth_epoch: int
    error_code: str | None
    actions: list[str]
    cpu: int
    memory_bytes: int
    pids_limit: int


class OperationOut(BaseModel):
    operation_id: uuid.UUID
    workspace_id: uuid.UUID
    state: str
    op: str
    error_code: str | None = None


class EntryTicketIn(BaseModel):
    target: str = Field(pattern=r"^(agent|files|terminal)$")


class EntryTicketOut(BaseModel):
    ticket: str
    workspace_host: str
    target: str
    expires_in: int


class TemplateOut(BaseModel):
    version: str
    image_digest: str
    dsh_version: str | None = None
    cpu: int
    memory_bytes: int
    pids_limit: int
    enabled: bool
