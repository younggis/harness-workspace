"""Platform metadata model (harness schema).

All tables use application-generated UUIDs and store timestamps in UTC.
No user-visible name is ever used in a container/volume/path name.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer,
    String, UniqueConstraint, Uuid, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(value: datetime | None, *, now: datetime | None = None) -> bool:
    """True if a stored timestamp is in the past.

    SQLite returns naive datetimes for DateTime(timezone=True); treat those as UTC
    so the same code path works for offline tests and PostgreSQL.
    """
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= (now or datetime.now(timezone.utc))


class Base(DeclarativeBase):
    pass


def new_id() -> uuid.UUID:
    return uuid.uuid4()


# ---- status vocabularies (kept as plain strings, no DB enum dependency) -----
USER_ACTIVE, USER_DISABLED = "active", "disabled"
TENANT_ACTIVE, TENANT_DISABLED = "active", "disabled"
MEMBER_ADMIN, MEMBER_MEMBER = "tenant_admin", "member"
MEMBER_ACTIVE, MEMBER_DISABLED = "active", "disabled"

DESIRED_RUNNING, DESIRED_STOPPED = "running", "stopped"
OBS_PROVISIONING, OBS_STARTING, OBS_RUNNING = "provisioning", "starting", "running"
OBS_STOPPING, OBS_STOPPED, OBS_ERROR = "stopping", "stopped", "error"

OP_START, OP_STOP, OP_REBUILD, OP_DISABLE, OP_ENABLE, OP_ALLOCATE = (
    "start", "stop", "rebuild", "disable", "enable", "allocate"
)
OP_QUEUED, OP_RUNNING, OP_SUCCEEDED, OP_FAILED = (
    "queued", "running", "succeeded", "failed"
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    login_norm: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=USER_ACTIVE, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(128), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=TENANT_ACTIVE, nullable=False)
    max_running: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    max_workspaces: Mapped[int] = mapped_column(Integer, default=16, nullable=False)
    daily_token_budget: Mapped[int] = mapped_column(Integer, default=1_000_000, nullable=False)
    # Tenant-declared container resource policy (CPU/RAM/PIDS; no GPU in this release).
    cpu_per_space: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    memory_per_space_bytes: Mapped[int] = mapped_column(BigInteger, default=1073741824, nullable=False)
    pids_per_space: Mapped[int] = mapped_column(Integer, default=256, nullable=False)
    max_total_cpu: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    max_total_memory_bytes: Mapped[int] = mapped_column(BigInteger, default=4294967296, nullable=False)
    max_total_pids: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Membership(Base):
    __tablename__ = "memberships"
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default=MEMBER_MEMBER, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=MEMBER_ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Template(Base):
    __tablename__ = "templates"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    version: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    image_digest: Mapped[str] = mapped_column(String(255), nullable=False)
    dsh_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    profile_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    cpu: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    memory_bytes: Mapped[int] = mapped_column(Integer, default=1073741824, nullable=False)
    pids_limit: Mapped[int] = mapped_column(Integer, default=256, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    template_version: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    desired_state: Mapped[str] = mapped_column(String(32), default=DESIRED_STOPPED, nullable=False)
    observed_state: Mapped[str] = mapped_column(String(32), default=OBS_STOPPED, nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    auth_epoch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Effective container resources. NULL means "inherit from template" (legacy rows).
    cpu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pids_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_id", name="uq_ws_tenant_owner"),
        UniqueConstraint("tenant_id", "id", name="uq_ws_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "owner_id"], ["memberships.tenant_id", "memberships.user_id"]),
        ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )


class WorkspaceOperation(Base):
    __tablename__ = "workspace_operations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workspaces.id"), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    op: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), default=OP_QUEUED, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_generation: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_op_ws_key"),
        Index("ix_op_state_lease", "state", "lease_until"),
        # At most one queued/running change per workspace (race-safe reconcile).
        Index(
            "uq_op_active_ws", "workspace_id", unique=True,
            postgresql_where=text("state IN ('queued','running')"),
            sqlite_where=text("state IN ('queued','running')"),
        ),
    )


class EntryTicket(Base):
    __tablename__ = "entry_tickets"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    ticket_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    auth_session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth_sessions.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workspaces.id"), nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkspaceSession(Base):
    __tablename__ = "workspace_sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    auth_session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("auth_sessions.id"), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workspaces.id"), nullable=False)
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class RuntimeCredential(Base):
    __tablename__ = "runtime_credentials"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("workspaces.id"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (
        # Exactly one active model token per workspace generation.
        Index(
            "uq_credential_active", "workspace_id", "generation", unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )


class ApiToken(Base):
    """Scoped bearer token for service accounts / automation."""
    __tablename__ = "api_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scopes: Mapped[str] = mapped_column(String(512), nullable=False)  # space-separated
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ModelRequest(Base):
    __tablename__ = "model_requests"
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    reserved_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_source: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BudgetBucket(Base):
    __tablename__ = "budget_buckets"
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    day: Mapped[str] = mapped_column(String(10), primary_key=True)  # UTC YYYY-MM-DD
    reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    __table_args__ = (Index("ix_audit_tenant_time", "tenant_id", "occurred_at"),)
