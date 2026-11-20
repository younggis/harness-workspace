"""Authentication, tenant selection and logout."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from harness_common import models as m
from harness_common.errors import APIError
from harness_common.security import (
    hash_password, new_token, sha256_text, token_hash, verify_password,
)

from .. import schemas as s
from ..deps import (
    CSRF_COOKIE, SESSION_COOKIE, DbSession, IdentityDep, SettingsDep,
)

router = APIRouter(prefix="/api")

SESSION_TTL_SECONDS = 8 * 3600


def _user_tenants(db, user_id) -> list[m.Tenant]:
    return list(db.execute(
        select(m.Tenant)
        .join(m.Membership, m.Membership.tenant_id == m.Tenant.id)
        .where(
            m.Membership.user_id == user_id,
            m.Membership.status == m.MEMBER_ACTIVE,
            m.Tenant.status == m.TENANT_ACTIVE,
        )
    ).scalars())


def _tenant_role(db, user_id, tenant_id) -> str:
    ms = db.execute(
        select(m.Membership).where(
            m.Membership.user_id == user_id,
            m.Membership.tenant_id == tenant_id,
            m.Membership.status == m.MEMBER_ACTIVE,
        )
    ).scalar_one_or_none()
    return ms.role if ms else ""


def _tenant_briefs(db, user_id, tenants) -> list[s.TenantBrief]:
    return [s.TenantBrief(id=t.id, slug=t.slug, name=t.name,
                          role=_tenant_role(db, user_id, t.id)) for t in tenants]


def _set_session_cookies(response: Response, session_token: str, csrf_token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE, session_token, max_age=SESSION_TTL_SECONDS,
        httponly=True, samesite="lax", secure=secure, path="/", domain=None,
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, max_age=SESSION_TTL_SECONDS,
        httponly=False, samesite="lax", secure=secure, path="/", domain=None,
    )


def _revoke_session_dependents(db, session: m.AuthSession) -> None:
    now = datetime.now(timezone.utc)
    for ws_sess in db.execute(
        select(m.WorkspaceSession).where(
            m.WorkspaceSession.auth_session_id == session.id,
            m.WorkspaceSession.revoked_at.is_(None),
        )
    ).scalars():
        ws_sess.revoked_at = now
    for ticket in db.execute(
        select(m.EntryTicket).where(
            m.EntryTicket.auth_session_id == session.id,
            m.EntryTicket.used_at.is_(None),
        )
    ).scalars():
        ticket.used_at = now  # consume so a stale tab cannot redeem


@router.post("/auth/login")
def login(body: s.LoginIn, request: Request, response: Response, db: DbSession, settings: SettingsDep):
    login_norm = body.login.strip().lower()
    limiter = request.app.state.login_limiter
    if not limiter.allowed(login_norm):
        request.app.state.metrics.inc("login_total", {"result": "rate_limited"})
        raise APIError("RATE_LIMITED", "Too many failed logins", retryable=True)

    user = db.execute(select(m.User).where(m.User.login_norm == login_norm)).scalar_one_or_none()
    if not user or user.status != m.USER_ACTIVE or not verify_password(user.password_hash, body.password):
        limiter.record_failure(login_norm)
        request.app.state.metrics.inc("login_total", {"result": "failure"})
        raise APIError("UNAUTHENTICATED", "Invalid credentials")  # generic message
    limiter.clear(login_norm)
    request.app.state.metrics.inc("login_total", {"result": "success"})

    # MFA: password alone is not a session when the user enrolled TOTP.
    if user.mfa_enabled and user.mfa_secret:
        from ..auth_oidc import sign_state
        ticket = new_token(24)
        signed = sign_state(f"{user.id}:{ticket}", settings.session_signing_key)
        resp = JSONResponse({"mfa_required": True})
        resp.set_cookie("harness_mfa", signed, max_age=300, httponly=True,
                        samesite="lax", path="/",
                        secure=str(settings.portal_origin).startswith("https://"))
        return resp

    tenants = _user_tenants(db, user.id)
    active = tenants[0].id if tenants else None
    session_token = new_token()
    csrf_token = new_token(24)
    auth = m.AuthSession(
        id=uuid.uuid4(),
        token_hash=token_hash(session_token),
        user_id=user.id,
        active_tenant_id=active,
        csrf_hash=token_hash(csrf_token),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL_SECONDS),
    )
    db.add(auth)
    db.add(m.AuditEvent(actor_id=user.id, action="auth.login", result="success",
                        request_id=request.state.request_id))
    db.commit()

    secure = str(settings.portal_origin).startswith("https://")
    _set_session_cookies(response, session_token, csrf_token, secure=secure)
    return s.LoginOut(
        user=s.UserBrief(id=user.id, login_norm=user.login_norm, display_name=user.display_name,
                         is_platform_admin=user.is_platform_admin),
        tenants=_tenant_briefs(db, user.id, tenants),
        active_tenant_id=active,
        csrf_token=csrf_token,
    )


@router.get("/me", response_model=s.MeOut)
def me(request: Request, identity: IdentityDep, db: DbSession):
    tenants = _user_tenants(db, identity.user.id)
    return s.MeOut(
        user=s.UserBrief(id=identity.user.id, login_norm=identity.user.login_norm,
                         display_name=identity.user.display_name,
                         is_platform_admin=identity.user.is_platform_admin),
        tenants=_tenant_briefs(db, identity.user.id, tenants),
        active_tenant_id=identity.tenant_id,
        csrf_token=request.cookies.get(CSRF_COOKIE, ""),
    )


@router.post("/auth/logout")
async def logout(request: Request, response: Response, identity: IdentityDep, db: DbSession):
    now = datetime.now(timezone.utc)
    identity.session.revoked_at = now
    _revoke_session_dependents(db, identity.session)
    db.add(m.AuditEvent(actor_id=identity.user.id, tenant_id=identity.tenant_id,
                        action="auth.logout", result="success", request_id=request.state.request_id))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    await request.app.state.connections.close_auth_session(identity.session.id)
    return {"status": "ok"}


@router.post("/auth/active-tenant", response_model=s.MeOut)
async def set_active_tenant(body: s.ActiveTenantIn, request: Request, response: Response, identity: IdentityDep, db: DbSession, settings: SettingsDep):
    membership = db.execute(
        select(m.Membership).where(
            m.Membership.tenant_id == body.tenant_id,
            m.Membership.user_id == identity.user.id,
            m.Membership.status == m.MEMBER_ACTIVE,
        )
    ).scalar_one_or_none()
    tenant = db.get(m.Tenant, body.tenant_id)
    if not membership or not tenant or tenant.status != m.TENANT_ACTIVE:
        raise APIError("FORBIDDEN", "No active membership for that tenant")
    # Switching tenant revokes all existing workspace sessions/tickets for this login.
    _revoke_session_dependents(db, identity.session)
    identity.session.active_tenant_id = body.tenant_id
    csrf_token = new_token(24)
    identity.session.csrf_hash = token_hash(csrf_token)
    db.commit()
    await request.app.state.connections.close_auth_session(identity.session.id)
    secure = str(settings.portal_origin).startswith("https://")
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=SESSION_TTL_SECONDS,
                        httponly=False, samesite="lax", secure=secure, path="/", domain=None)
    tenants = _user_tenants(db, identity.user.id)
    return s.MeOut(
        user=s.UserBrief(id=identity.user.id, login_norm=identity.user.login_norm,
                         display_name=identity.user.display_name,
                         is_platform_admin=identity.user.is_platform_admin),
        tenants=_tenant_briefs(db, identity.user.id, tenants),
        active_tenant_id=body.tenant_id,
        csrf_token=csrf_token,
    )
