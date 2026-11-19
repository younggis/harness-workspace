"""TOTP MFA enrollment, verification and login completion."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from harness_common import models as m
from harness_common.config import Settings, get_settings
from harness_common.errors import APIError
from harness_common.security import new_token, token_hash

from .. import auth_oidc
from ..deps import CSRF_COOKIE, SESSION_COOKIE, CsrfDep, DbSession, IdentityDep, SettingsDep
from .auth import _set_session_cookies, _user_tenants

router = APIRouter(prefix="/api/auth/mfa")


@router.post("/enroll")
def enroll(request: Request, db: DbSession, identity: IdentityDep, _csrf: CsrfDep,
           settings: Settings = Depends(get_settings)):
    secret = pyotp.random_base32()
    identity.user.mfa_secret = secret
    identity.user.mfa_enabled = False
    db.add(m.AuditEvent(actor_id=identity.user.id, action="mfa.enroll", result="success",
                        request_id=request.state.request_id))
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=identity.user.login_norm, issuer_name="Harness Workspace")
    return {"secret": secret, "otpauth_uri": uri, "enabled": False}


@router.post("/verify")
def verify(request: Request, body: dict, db: DbSession, identity: IdentityDep, _csrf: CsrfDep):
    code = str(body.get("code", "")).strip()
    if not identity.user.mfa_secret:
        raise APIError("CONFLICT", "MFA is not enrolled")
    if not pyotp.TOTP(identity.user.mfa_secret).verify(code, valid_window=1):
        raise APIError("FORBIDDEN", "Invalid MFA code")
    identity.user.mfa_enabled = True
    db.add(m.AuditEvent(actor_id=identity.user.id, action="mfa.enable", result="success",
                        request_id=request.state.request_id))
    db.commit()
    return {"enabled": True}


@router.post("/disable")
def disable(request: Request, body: dict, db: DbSession, identity: IdentityDep, _csrf: CsrfDep):
    code = str(body.get("code", "")).strip()
    if not identity.user.mfa_secret or not pyotp.TOTP(identity.user.mfa_secret).verify(code, valid_window=1):
        raise APIError("FORBIDDEN", "Invalid MFA code")
    identity.user.mfa_enabled = False
    identity.user.mfa_secret = None
    db.add(m.AuditEvent(actor_id=identity.user.id, action="mfa.disable", result="success",
                        request_id=request.state.request_id))
    db.commit()
    return {"enabled": False}


@router.post("/complete")
def complete(body: dict, response: Response, db: DbSession, settings: SettingsDep,
             request: Request):
    raw = auth_oidc.verify_state(request.cookies.get("harness_mfa", ""), settings.session_signing_key)
    if not raw or ":" not in raw:
        raise APIError("UNAUTHENTICATED", "MFA ticket invalid or expired")
    uid, _ticket = raw.split(":", 1)
    try:
        uid = uuid.UUID(uid)
    except ValueError:
        raise APIError("UNAUTHENTICATED", "MFA ticket invalid")
    user = db.get(m.User, uid)
    if not user or not user.mfa_enabled or not user.mfa_secret:
        raise APIError("UNAUTHENTICATED", "MFA not enabled")
    if not pyotp.TOTP(user.mfa_secret).verify(str(body.get("code", "")).strip(), valid_window=1):
        raise APIError("FORBIDDEN", "Invalid MFA code")

    tenants = _user_tenants(db, user.id)
    active = tenants[0].id if tenants else None
    token, csrf = new_token(), new_token(24)
    db.add(m.AuthSession(
        id=uuid.uuid4(), token_hash=token_hash(token), user_id=user.id,
        active_tenant_id=active, csrf_hash=token_hash(csrf),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=8),
    ))
    db.add(m.AuditEvent(actor_id=user.id, action="auth.mfa.complete", result="success",
                        request_id=request.state.request_id))
    db.commit()
    response.delete_cookie("harness_mfa", path="/")
    secure = str(settings.portal_origin).startswith("https://")
    _set_session_cookies(response, token, csrf, secure=secure)
    return {
        "user": {"id": str(user.id), "login_norm": user.login_norm,
                 "display_name": user.display_name, "is_platform_admin": user.is_platform_admin},
        "tenants": [{"id": str(t.id), "slug": t.slug, "name": t.name} for t in tenants],
        "active_tenant_id": str(active) if active else None,
        "csrf_token": csrf,
    }
