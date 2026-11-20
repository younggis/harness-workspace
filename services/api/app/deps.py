"""Shared FastAPI dependencies: DB session, request context, auth and CSRF."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from harness_common import models as m
from harness_common.config import Settings, get_settings
from harness_common.errors import APIError
from harness_common.security import constant_time_eq, token_hash

SESSION_COOKIE = "harness_session"
CSRF_COOKIE = "harness_csrf"


@dataclass
class Identity:
    user: m.User
    session: m.AuthSession
    tenant_id: uuid.UUID | None
    role: str | None  # tenant_admin | member | None (platform admin uses flag on user)
    scopes: frozenset[str] = frozenset()
    is_api_token: bool = False

    @property
    def is_platform_admin(self) -> bool:
        return bool(self.user.is_platform_admin)


def get_db(request: Request) -> Session:
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        # close() also rolls back, but an explicit rollback makes the intent
        # clear and guarantees no idle transaction is left holding locks.
        if session.in_transaction():
            session.rollback()
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_ws_db(websocket) -> Session:
    factory = websocket.app.state.session_factory
    session = factory()
    try:
        yield session
    finally:
        session.close()


WsDbSession = Annotated[Session, Depends(get_ws_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def current_identity(
    request: Request,
    db: DbSession,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Identity:
    # Service-account authentication: scoped API tokens. No browser session,
    # no CSRF; authorization is enforced purely by scope via require_permission.
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:].strip()
        tok = db.execute(
            select(m.ApiToken).where(m.ApiToken.token_hash == token_hash(raw))
        ).scalar_one_or_none()
        if not tok or tok.revoked_at is not None or m.is_expired(tok.expires_at):
            raise APIError("UNAUTHENTICATED", "Invalid API token")
        user = db.get(m.User, tok.user_id)
        if not user or user.status != m.USER_ACTIVE:
            raise APIError("UNAUTHENTICATED", "Account disabled")
        role = None
        if tok.tenant_id is not None:
            ms = db.execute(
                select(m.Membership).where(
                    m.Membership.tenant_id == tok.tenant_id,
                    m.Membership.user_id == user.id,
                )
            ).scalar_one_or_none()
            if ms and ms.status == m.MEMBER_ACTIVE:
                role = ms.role
        now = datetime.now(timezone.utc)
        last = tok.last_used_at
        if last is not None and last.tzinfo is None:  # SQLite returns naive datetimes
            last = last.replace(tzinfo=timezone.utc)
        if last is None or now - last > timedelta(minutes=1):
            tok.last_used_at = now
            db.commit()
        return Identity(
            user=user, session=None, tenant_id=tok.tenant_id, role=role,
            scopes=frozenset(tok.scopes.split()), is_api_token=True,
        )

    if not session_token:
        raise APIError("UNAUTHENTICATED", "Not authenticated")
    row = db.execute(
        select(m.AuthSession, m.User)
        .join(m.User, m.User.id == m.AuthSession.user_id)
        .where(m.AuthSession.token_hash == token_hash(session_token))
    ).first()
    if not row:
        raise APIError("UNAUTHENTICATED", "Not authenticated")
    auth, user = row
    if auth.revoked_at is not None or m.is_expired(auth.expires_at):
        raise APIError("UNAUTHENTICATED", "Session expired")
    if user.status != m.USER_ACTIVE:
        raise APIError("UNAUTHENTICATED", "Account disabled")

    role = None
    tenant_id = auth.active_tenant_id
    if tenant_id is not None:
        ms = db.execute(
            select(m.Membership).where(
                m.Membership.tenant_id == tenant_id,
                m.Membership.user_id == user.id,
            )
        ).scalar_one_or_none()
        if not ms or ms.status != m.MEMBER_ACTIVE:
            raise APIError("FORBIDDEN", "No active membership for the active tenant")
        role = ms.role
    return Identity(user=user, session=auth, tenant_id=tenant_id, role=role)


IdentityDep = Annotated[Identity, Depends(current_identity)]


def optional_identity(
    request: Request,
    db: DbSession,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> Identity | None:
    try:
        return current_identity(request, db, session_token)
    except APIError:
        return None


def require_csrf(
    request: Request,
    identity: IdentityDep,
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    # Double-submit must use the header. Accepting the cookie as a fallback
    # defeats the purpose (a browser sends cookies automatically). API tokens
    # are Bearer-authenticated and do not need CSRF protection.
    if identity.is_api_token:
        return
    if not csrf_header or not constant_time_eq(identity.session.csrf_hash, token_hash(csrf_header)):
        raise APIError("FORBIDDEN", "Invalid CSRF token")


CsrfDep = Annotated[None, Depends(require_csrf)]


def require_platform_admin(identity: IdentityDep) -> Identity:
    if identity.is_api_token:
        return identity  # the endpoint's require_permission(...) is authoritative
    if not identity.is_platform_admin:
        raise APIError("FORBIDDEN", "Platform administrator required")
    return identity


PlatformAdminDep = Annotated[Identity, Depends(require_platform_admin)]


def require_tenant_admin(identity: IdentityDep) -> Identity:
    if identity.is_api_token:
        return identity  # the endpoint's require_permission(...) is authoritative
    if identity.is_platform_admin:
        return identity
    if identity.role != m.MEMBER_ADMIN or identity.tenant_id is None:
        raise APIError("FORBIDDEN", "Tenant administrator required")
    return identity


TenantAdminDep = Annotated[Identity, Depends(require_tenant_admin)]


def require_idempotency(idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> str:
    if not idempotency_key or len(idempotency_key) > 128:
        raise APIError("CONFLICT", "Idempotency-Key header is required")
    return idempotency_key


IdempotencyDep = Annotated[str, Depends(require_idempotency)]
