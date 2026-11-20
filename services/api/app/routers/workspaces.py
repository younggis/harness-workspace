"""Workspace allocation, lifecycle actions and operation polling."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from harness_common import models as m
from harness_common.errors import APIError
from harness_common.security import sha256_text

from .. import schemas as s
from ..deps import (
    DbSession, IdempotencyDep, IdentityDep, PlatformAdminDep, TenantAdminDep,
)
from ..resources import check_running_totals, resolve_space_resources

router = APIRouter(prefix="/api")

ALLOWED_ACTIONS = {"start", "stop", "rebuild", "disable", "enable"}
ADMIN_ACTIONS = {"rebuild", "disable", "enable"}


def _can_see(identity, workspace: m.Workspace) -> bool:
    if identity.is_platform_admin:
        return True
    if identity.tenant_id != workspace.tenant_id:
        return False
    if identity.role == m.MEMBER_ADMIN:
        return True
    return workspace.owner_id == identity.user.id


def _get_visible_workspace(db, identity, wid: uuid.UUID) -> m.Workspace:
    ws = db.get(m.Workspace, wid)
    if not ws or not _can_see(identity, ws):
        raise APIError("NOT_FOUND", "Workspace not found")  # uniform 404
    return ws


def _workspace_out(ws: m.Workspace, identity, tenant: m.Tenant | None = None) -> s.WorkspaceOut:
    actions: list[str] = []
    if identity.is_platform_admin or identity.role == m.MEMBER_ADMIN:
        actions = ["start", "stop", "rebuild", "disable", "enable"]
    elif ws.owner_id == identity.user.id:
        actions = ["start", "stop"]
    return s.WorkspaceOut(
        id=ws.id, tenant_id=ws.tenant_id, owner_id=ws.owner_id,
        template_version=ws.template_version, enabled=ws.enabled,
        desired_state=ws.desired_state, observed_state=ws.observed_state,
        generation=ws.generation, auth_epoch=ws.auth_epoch, error_code=ws.error_code,
        actions=[a for a in actions if ws.enabled or a in ("enable", "disable")],
        cpu=ws.cpu if ws.cpu is not None else (tenant.cpu_per_space if tenant else 1),
        memory_bytes=ws.memory_bytes if ws.memory_bytes is not None else
            (tenant.memory_per_space_bytes if tenant else 1073741824),
        pids_limit=ws.pids_limit if ws.pids_limit is not None else
            (tenant.pids_per_space if tenant else 256),
    )


@router.post("/admin/tenants/{tid}/workspaces", response_model=s.WorkspaceOut, status_code=201)
def allocate_workspace(tid: uuid.UUID, body: s.CreateWorkspaceIn, request: Request,
                       db: DbSession, identity: TenantAdminDep,
                       idempotency_key: IdempotencyDep):
    if not identity.is_platform_admin and identity.tenant_id != tid:
        raise APIError("NOT_FOUND", "Tenant not found")
    tenant = db.get(m.Tenant, tid)
    if not tenant or tenant.status != m.TENANT_ACTIVE:
        raise APIError("NOT_FOUND", "Tenant not found")
    membership = db.get(m.Membership, (tid, body.owner_id))
    if not membership or membership.status != m.MEMBER_ACTIVE:
        raise APIError("CONFLICT", "Owner must be an active member of the tenant")
    tpl = db.execute(
        select(m.Template).where(m.Template.version == body.template_version, m.Template.enabled.is_(True))
    ).scalar_one_or_none()
    if not tpl:
        raise APIError("CONFLICT", "Template version is not available")

    # Idempotent allocation under unique (tenant_id, owner_id).
    existing = db.execute(
        select(m.Workspace).where(m.Workspace.tenant_id == tid, m.Workspace.owner_id == body.owner_id)
    ).scalar_one_or_none()
    if existing:
        return _workspace_out(existing, identity, tenant)

    count = db.execute(
        select(func.count()).select_from(m.Workspace).where(m.Workspace.tenant_id == tid)
    ).scalar_one()
    if count >= tenant.max_workspaces:
        raise APIError("RATE_LIMITED", "Workspace quota exceeded")

    cpu, memory_bytes, pids_limit = resolve_space_resources(
        tenant, cpu=body.cpu, memory=body.memory_bytes, pids=body.pids_limit,
    )
    ws = m.Workspace(id=uuid.uuid4(), tenant_id=tid, owner_id=body.owner_id,
                     template_version=body.template_version,
                     cpu=cpu, memory_bytes=memory_bytes, pids_limit=pids_limit)
    db.add(ws)
    db.add(m.AuditEvent(actor_id=identity.user.id, tenant_id=tid,
                        workspace_id=ws.id, action="workspace.allocate",
                        target=str(body.owner_id), result="success",
                        request_id=request.state.request_id))
    db.commit()
    return _workspace_out(ws, identity, tenant)


@router.get("/workspaces", response_model=list[s.WorkspaceOut])
def list_workspaces(db: DbSession, identity: IdentityDep):
    if identity.is_platform_admin:
        # The workbench shows only spaces the account owns. Admin-wide views
        # live under /admin; management privilege never grants file/PTY access.
        rows = db.execute(select(m.Workspace).where(m.Workspace.owner_id == identity.user.id)).scalars()
    elif identity.role == m.MEMBER_ADMIN and identity.tenant_id:
        rows = db.execute(select(m.Workspace).where(m.Workspace.tenant_id == identity.tenant_id)).scalars()
    else:
        rows = db.execute(select(m.Workspace).where(m.Workspace.owner_id == identity.user.id)).scalars()
    tenants = {t.id: t for t in db.execute(select(m.Tenant)).scalars()}
    return [_workspace_out(ws, identity, tenants.get(ws.tenant_id)) for ws in rows]


@router.get("/workspaces/{wid}", response_model=s.WorkspaceOut)
def get_workspace(wid: uuid.UUID, db: DbSession, identity: IdentityDep):
    ws = _get_visible_workspace(db, identity, wid)
    return _workspace_out(ws, identity, db.get(m.Tenant, ws.tenant_id))


@router.post("/workspaces/{wid}/actions/{action}", response_model=s.OperationOut, status_code=202)
async def workspace_action(wid: uuid.UUID, action: str, request: Request, db: DbSession,
                           identity: IdentityDep, idempotency_key: IdempotencyDep):
    if action not in ALLOWED_ACTIONS:
        raise APIError("NOT_FOUND", "Unknown action")
    ws = _get_visible_workspace(db, identity, wid)

    owner_only = ws.owner_id == identity.user.id
    if action in ADMIN_ACTIONS and not (identity.is_platform_admin or identity.role == m.MEMBER_ADMIN):
        raise APIError("FORBIDDEN", "Administrator required for this action")
    if action in ("start", "stop") and not (owner_only or identity.is_platform_admin or identity.role == m.MEMBER_ADMIN):
        raise APIError("FORBIDDEN", "Workspace owner or administrator required")
    if action in ("start", "enable") and not ws.enabled and action == "start":
        raise APIError("CONFLICT", "Workspace is disabled")

    request_hash = sha256_text(f"{action}:{wid}:{identity.user.id}:{ws.generation}")
    existing = db.execute(
        select(m.WorkspaceOperation).where(
            m.WorkspaceOperation.workspace_id == wid,
            m.WorkspaceOperation.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()
    if existing:
        if existing.request_hash != request_hash:
            raise APIError("CONFLICT", "Idempotency-Key reused with different parameters")
        return s.OperationOut(operation_id=existing.id, workspace_id=wid,
                              state=existing.state, op=existing.op, error_code=existing.error_code)

    # Enforce running quota for start (counts reserved starting/provisioning/running).
    if action == "start":
        tenant = db.get(m.Tenant, ws.tenant_id)
        running = db.execute(
            select(func.count()).select_from(m.Workspace).where(
                m.Workspace.tenant_id == ws.tenant_id,
                m.Workspace.id != ws.id,
                m.Workspace.desired_state == m.DESIRED_RUNNING,
            )
        ).scalar_one()
        if running >= tenant.max_running:
            raise APIError("RATE_LIMITED", "Running workspace quota exceeded")
        check_running_totals(db, tenant, ws)

    target_generation = ws.generation + 1 if action == "rebuild" else ws.generation
    op = m.WorkspaceOperation(
        id=uuid.uuid4(), workspace_id=wid, actor_id=identity.user.id, op=action,
        idempotency_key=idempotency_key, request_hash=request_hash,
        state=m.OP_QUEUED, target_generation=target_generation,
    )
    db.add(op)

    if action == "start":
        ws.desired_state = m.DESIRED_RUNNING
    elif action in ("stop", "disable"):
        ws.desired_state = m.DESIRED_STOPPED
        if action == "disable":
            ws.enabled = False
            ws.auth_epoch += 1
    elif action == "enable":
        ws.enabled = True
        ws.auth_epoch += 1
    elif action == "rebuild":
        ws.generation = target_generation
        ws.auth_epoch += 1

    db.add(m.AuditEvent(actor_id=identity.user.id, tenant_id=ws.tenant_id, workspace_id=wid,
                        action=f"workspace.{action}", result="success",
                        request_id=request.state.request_id))
    db.commit()
    # Stop/disable must close live WS/terminal/SSE within 3 seconds.
    if action in (m.OP_STOP, m.OP_DISABLE):
        await request.app.state.connections.close_workspace(wid)
    return s.OperationOut(operation_id=op.id, workspace_id=wid, state=op.state, op=op.op)


@router.get("/operations/{oid}", response_model=s.OperationOut)
def get_operation(oid: uuid.UUID, db: DbSession, identity: IdentityDep):
    op = db.get(m.WorkspaceOperation, oid)
    if not op:
        raise APIError("NOT_FOUND", "Operation not found")
    ws = _get_visible_workspace(db, identity, op.workspace_id)
    return s.OperationOut(operation_id=op.id, workspace_id=ws.id, state=op.state,
                          op=op.op, error_code=op.error_code)
