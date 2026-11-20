"""Enterprise OIDC login: authorization-code + PKCE, JIT user provisioning."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from harness_common import models as m
from harness_common.config import Settings, get_settings
from harness_common.errors import APIError
from harness_common.security import hash_password, new_token, token_hash

from .. import auth_oidc
from ..deps import CSRF_COOKIE, SESSION_COOKIE

router = APIRouter(prefix="/api/auth/oidc")
STATE_COOKIE = "harness_oidc_state"
STATE_TTL = 300
SESSION_TTL = 8 * 3600


@router.get("/config")
def oidc_config(settings: Settings = Depends(get_settings)):
    return {"enabled": auth_oidc.enabled(settings.oidc_issuer, settings.oidc_client_id)}


@router.get("/start")
def start(request: Request, settings: Settings = Depends(get_settings)):
    if not auth_oidc.enabled(settings.oidc_issuer, settings.oidc_client_id):
        raise APIError("UNAVAILABLE", "OIDC is not configured")
    state, nonce, verifier = new_token(16), new_token(16), new_token(32)
    signed = auth_oidc.sign_state(f"{state}:{nonce}:{verifier}", settings.session_signing_key)
    url = auth_oidc.authorize_url(settings.oidc_issuer, settings.oidc_client_id,
                                  settings.oidc_redirect_uri, state, nonce, verifier)
    resp = RedirectResponse(url=url, status_code=302)
    resp.set_cookie(STATE_COOKIE, signed, max_age=STATE_TTL, httponly=True,
                    samesite="lax", secure=str(settings.portal_origin).startswith("https://"), path="/")
    return resp


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None,
             error: str | None = None, settings: Settings = Depends(get_settings)):
    if error or not code or not state:
        raise APIError("UNAUTHENTICATED", "OIDC login cancelled or failed")
    raw = auth_oidc.verify_state_rotated(request.cookies.get(STATE_COOKIE, ""), settings)
    if not raw:
        raise APIError("UNAUTHENTICATED", "Invalid OIDC state")
    state_v, nonce, verifier = raw.split(":", 2)
    if state_v != state:
        raise APIError("FORBIDDEN", "OIDC state mismatch")
    tokens = auth_oidc.exchange_code(settings.oidc_issuer, settings.oidc_client_id,
                                     settings.oidc_client_secret, settings.oidc_redirect_uri,
                                     code, verifier)
    id_token = tokens.get("id_token")
    if not id_token:
        raise APIError("UNAUTHENTICATED", "OIDC provider returned no id_token")
    claims = auth_oidc.verify_id_token(settings.oidc_issuer, settings.oidc_client_id,
                                       id_token, nonce)
    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        raise APIError("UNAUTHENTICATED", "OIDC identity has no email")

    from ..deps import get_db
    db = next(get_db(request))
    try:
        user = db.execute(select(m.User).where(m.User.login_norm == email)).scalar_one_or_none()
        if not user:
            if not settings.oidc_auto_provision:
                raise APIError("FORBIDDEN", "Account not provisioned; contact an administrator")
            user = m.User(id=uuid.uuid4(), login_norm=email,
                          display_name=claims.get("name") or email.split("@")[0],
                          password_hash=hash_password(new_token(24)), is_platform_admin=False)
            db.add(user); db.flush()
        if user.status != m.USER_ACTIVE:
            raise APIError("FORBIDDEN", "Account disabled")

        tenant = db.execute(select(m.Tenant).join(m.Membership).where(
            m.Membership.user_id == user.id, m.Tenant.status == m.TENANT_ACTIVE
        )).scalar_one_or_none()
        token, csrf = new_token(), new_token(24)
        db.add(m.AuthSession(
            id=uuid.uuid4(), token_hash=token_hash(token), user_id=user.id,
            active_tenant_id=tenant.id if tenant else None, csrf_hash=token_hash(csrf),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=SESSION_TTL),
        ))
        db.add(m.AuditEvent(actor_id=user.id, action="auth.oidc.login", target=email,
                            result="success", request_id=request.state.request_id))
        db.commit()
    finally:
        db.close()

    secure = str(settings.portal_origin).startswith("https://")
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(STATE_COOKIE, path="/")
    resp.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, httponly=True,
                    samesite="lax", secure=secure, path="/")
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=SESSION_TTL, httponly=False,
                    samesite="lax", secure=secure, path="/")
    return resp
