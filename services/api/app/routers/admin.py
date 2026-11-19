"""Tenant, membership, user, template, usage and audit administration."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from harness_common import models as m
from harness_common.errors import APIError
from harness_common.security import hash_password

from .. import schemas as s
from ..deps import (
    DbSession, IdentityDep, PlatformAdminDep, TenantAdminDep,
)

router = APIRouter(prefix="/api")


def _require_tenant_scope(identity, tenant_id: uuid.UUID) -> None:
    if identity.is_platform_admin:
        return
    if identity.tenant_id != tenant_id or identity.role != m.MEMBER_ADMIN:
        raise APIError("NOT_FOUND", "Tenant not found")


@router.post("/admin/tenants", response_model=s.TenantBrief, status_code=201)
def create_tenant(body: s.CreateTenantIn, request: Request, db: DbSession, _admin: PlatformAdminDep):
    if db.execute(select(m.Tenant).where(m.Tenant.slug == body.slug)).scalar_one_or_none():
        raise APIError("CONFLICT", "Tenant slug already exists")
    tenant = m.Tenant(
        id=uuid.uuid4(), slug=body.slug, name=body.name,
        max_running=body.max_running, max_workspaces=body.max_workspaces,
        daily_token_budget=body.daily_token_budget,
    )
    db.add(tenant)
    db.add(m.AuditEvent(actor_id=_admin.user.id, action="tenant.create", target=body.slug,
                        result="success", request_id=request.state.request_id))
    db.commit()
    return s.TenantBrief(id=tenant.id, slug=tenant.slug, name=tenant.name)


@router.get("/admin/tenants")
def list_tenants(db: DbSession, _admin: PlatformAdminDep,
                 cursor: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    rows = db.execute(select(m.Tenant).order_by(m.Tenant.created_at).offset(cursor).limit(limit)).scalars()
    return {"items": [
        {"id": str(t.id), "slug": t.slug, "name": t.name, "status": t.status,
         "max_running": t.max_running, "max_workspaces": t.max_workspaces}
        for t in rows
    ], "cursor": cursor, "limit": limit}


@router.patch("/admin/tenants/{tid}")
async def patch_tenant(tid: uuid.UUID, body: s.PatchTenantIn, request: Request,
                       db: DbSession, _admin: PlatformAdminDep):
    tenant = db.get(m.Tenant, tid)
    if not tenant:
        raise APIError("NOT_FOUND", "Tenant not found")
    for field in ("name", "status", "max_running", "max_workspaces", "daily_token_budget"):
        value = getattr(body, field)
        if value is not None:
            setattr(tenant, field, value)
    db.add(m.AuditEvent(actor_id=_admin.user.id, tenant_id=tid, action="tenant.patch",
                        result="success", request_id=request.state.request_id))
    db.commit()
    if tenant.status != m.TENANT_ACTIVE:
        ids = set(db.execute(select(m.Workspace.id).where(m.Workspace.tenant_id == tid)).scalars())
        await request.app.state.connections.close_workspaces(ids)
    return {"id": str(tenant.id), "status": tenant.status, "name": tenant.name}


@router.post("/admin/users", response_model=s.UserBrief, status_code=201)
def create_user(body: s.CreateUserIn, request: Request, db: DbSession, _admin: PlatformAdminDep):
    login_norm = body.login.strip().lower()
    if db.execute(select(m.User).where(m.User.login_norm == login_norm)).scalar_one_or_none():
        raise APIError("CONFLICT", "Login already exists")
    user = m.User(
        id=uuid.uuid4(), login_norm=login_norm, display_name=body.display_name,
        password_hash=hash_password(body.password), is_platform_admin=body.is_platform_admin,
    )
    db.add(user)
    db.add(m.AuditEvent(actor_id=_admin.user.id, action="user.create", target=login_norm,
                        result="success", request_id=request.state.request_id))
    db.commit()
    return s.UserBrief(id=user.id, login_norm=user.login_norm, display_name=user.display_name,
                       is_platform_admin=user.is_platform_admin)


@router.put("/admin/tenants/{tid}/members/{uid}")
async def set_member(tid: uuid.UUID, uid: uuid.UUID, body: s.SetMemberIn, request: Request,
                     db: DbSession, identity: TenantAdminDep):
    _require_tenant_scope(identity, tid)
    target = db.get(m.User, uid)
    if not target or target.is_platform_admin and body.role == m.MEMBER_MEMBER:
        raise APIError("FORBIDDEN", "Cannot demote a platform administrator via membership")
    ms = db.get(m.Membership, (tid, uid))
    if ms is None:
        ms = m.Membership(tenant_id=tid, user_id=uid)
        db.add(ms)
    ms.role = body.role
    ms.status = body.status
    # Never demote/disable the LAST active tenant admin. Adding a member is fine.
    if body.role != m.MEMBER_ADMIN or body.status != m.MEMBER_ACTIVE:
        active_admins = db.execute(
            select(func.count()).select_from(m.Membership).where(
                m.Membership.tenant_id == tid,
                m.Membership.role == m.MEMBER_ADMIN,
                m.Membership.status == m.MEMBER_ACTIVE,
            )
        ).scalar_one()
        target_is_active_admin = (ms.role == m.MEMBER_ADMIN and ms.status == m.MEMBER_ACTIVE)
        if target_is_active_admin and active_admins <= 1:
            raise APIError("CONFLICT", "Cannot remove the last active tenant administrator")
        if active_admins == 0:
            raise APIError("CONFLICT", "Tenant must retain an active administrator")
    db.add(m.AuditEvent(actor_id=identity.user.id, tenant_id=tid, target=str(uid),
                        action="membership.set", result="success", request_id=request.state.request_id))
    db.commit()
    if body.status != m.MEMBER_ACTIVE:
        await request.app.state.connections.close_user(uid)
    return {"tenant_id": str(tid), "user_id": str(uid), "role": ms.role, "status": ms.status}


@router.get("/templates", response_model=list[s.TemplateOut])
def list_templates(db: DbSession, _identity: IdentityDep):
    rows = db.execute(select(m.Template).where(m.Template.enabled.is_(True))).scalars()
    return [s.TemplateOut(version=t.version, image_digest=t.image_digest,
                          dsh_version=t.dsh_version, cpu=t.cpu,
                          memory_bytes=t.memory_bytes, pids_limit=t.pids_limit, enabled=t.enabled)
            for t in rows]


@router.post("/admin/templates", response_model=s.TemplateOut, status_code=201)
def register_template(body: dict, request: Request, db: DbSession, _admin: PlatformAdminDep):
    version = str(body.get("version", ""))
    digest = str(body.get("image_digest", ""))
    if not version or not digest.startswith("sha256:"):
        raise APIError("CONFLICT", "A pinned sha256 image digest is required")
    if db.execute(select(m.Template).where(m.Template.version == version)).scalar_one_or_none():
        raise APIError("CONFLICT", "Template version already published (versions are immutable)")
    tpl = m.Template(
        id=uuid.uuid4(), version=version, image_digest=digest,
        dsh_version=str(body.get("dsh_version", "0.2.2-rc.4")),
        profile_hash=str(body.get("profile_hash", "")),
        cpu=int(body.get("cpu", 1)), memory_bytes=int(body.get("memory_bytes", 1073741824)),
        pids_limit=int(body.get("pids_limit", 256)),
    )
    db.add(tpl)
    db.add(m.AuditEvent(actor_id=_admin.user.id, action="template.register", target=version,
                        result="success", request_id=request.state.request_id))
    db.commit()
    return s.TemplateOut(version=tpl.version, image_digest=tpl.image_digest,
                         dsh_version=tpl.dsh_version, cpu=tpl.cpu,
                         memory_bytes=tpl.memory_bytes, pids_limit=tpl.pids_limit, enabled=tpl.enabled)


@router.get("/admin/tenants/{tid}/usage")
def tenant_usage(tid: uuid.UUID, db: DbSession, identity: IdentityDep,
                 start: str | None = None, end: str | None = None):
    _require_tenant_scope(identity, tid)
    rows = db.execute(
        select(m.ModelRequest.model, func.count(), func.sum(m.ModelRequest.input_tokens),
               func.sum(m.ModelRequest.output_tokens))
        .where(m.ModelRequest.tenant_id == tid)
        .group_by(m.ModelRequest.model)
    ).all()
    return {"tenant_id": str(tid), "source": "model_requests",
            "items": [{"model": r[0], "requests": r[1], "input_tokens": r[2] or 0,
                       "output_tokens": r[3] or 0} for r in rows],
            "unknown_usage": db.execute(
                select(func.count()).select_from(m.ModelRequest).where(
                    m.ModelRequest.usage_source == "unknown")
            ).scalar_one()}


@router.get("/admin/tenants/{tid}/audit")
def tenant_audit(tid: uuid.UUID, db: DbSession, identity: IdentityDep,
                 cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
    _require_tenant_scope(identity, tid)
    rows = db.execute(
        select(m.AuditEvent).where(m.AuditEvent.tenant_id == tid)
        .order_by(m.AuditEvent.occurred_at.desc()).offset(cursor).limit(limit)
    ).scalars()
    return {"items": [{"id": str(e.id), "occurred_at": e.occurred_at.isoformat(),
                       "actor_id": str(e.actor_id) if e.actor_id else None,
                       "action": e.action, "target": e.target, "result": e.result}
                      for e in rows], "cursor": cursor, "limit": limit}
