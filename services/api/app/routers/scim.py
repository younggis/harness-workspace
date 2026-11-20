"""Minimal SCIM 2.0 User resource for IdP provisioning.

Bearer token from SCIM_BEARER_TOKEN (or SCIM_BEARER_TOKEN_FILE). Disabled when blank.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from harness_common import models as m
from harness_common.config import Settings, get_settings
from harness_common.errors import APIError
from harness_common.security import hash_password, constant_time_eq, token_hash

from ..deps import DbSession

router = APIRouter(prefix="/scim/v2")
SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"


def _auth(request: Request) -> None:
    settings = request.app.state.settings
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        raise APIError("UNAUTHENTICATED", "Invalid SCIM token")
    # Static maintainer token (legacy) or a scoped API token.
    if settings.scim_bearer_token and constant_time_eq(token, settings.scim_bearer_token):
        return
    factory = request.app.state.session_factory
    try:
        with factory() as db:
            row = db.execute(select(m.ApiToken).where(
                m.ApiToken.token_hash == token_hash(token),
                m.ApiToken.revoked_at.is_(None),
                m.ApiToken.expires_at > datetime.now(timezone.utc),
            )).scalar_one_or_none()
            if row and "scim:write" in row.scopes.split():
                row.last_used_at = datetime.now(timezone.utc)
                db.commit()
                return
    except Exception:
        pass
    if not settings.scim_bearer_token:
        raise APIError("UNAVAILABLE", "SCIM is not configured")
    raise APIError("UNAUTHENTICATED", "Invalid SCIM token")


def _scim_user(u: m.User) -> dict:
    return {
        "schemas": [SCHEMA], "id": str(u.id), "userName": u.login_norm,
        "displayName": u.display_name, "active": u.status == m.USER_ACTIVE,
        "meta": {"resourceType": "User", "created": u.created_at.isoformat()},
    }


@router.get("/Users")
def list_users(request: Request, db: DbSession, filter: str | None = None,
               startIndex: int = 1, count: int = 100,
               _auth=Depends(_auth)):
    q = select(m.User).order_by(m.User.created_at)
    if filter and "userName eq" in filter:
        name = filter.split("eq", 1)[1].strip().strip('"').lower()
        q = q.where(m.User.login_norm == name)
    rows = db.execute(q.offset(max(0, startIndex - 1)).limit(min(count, 200))).scalars()
    return {"schemas": ["urn:ietf:params:scim:api:messages:2.0:ListResponse"],
            "totalResults": db.query(m.User).count(),
            "Resources": [_scim_user(u) for u in rows]}


@router.post("/Users", status_code=201)
async def create_user(request: Request, db: DbSession, _auth=Depends(_auth)):
    body = await request.json()
    name = str(body.get("userName", "")).strip().lower()
    if not name:
        raise APIError("CONFLICT", "userName is required")
    if db.execute(select(m.User).where(m.User.login_norm == name)).scalar_one_or_none():
        raise APIError("CONFLICT", "User already exists", status=409)
    import secrets
    user = m.User(id=uuid.uuid4(), login_norm=name,
                  display_name=str(body.get("displayName") or name),
                  password_hash=hash_password(secrets.token_urlsafe(24)),
                  is_platform_admin=False)
    db.add(user)
    db.add(m.AuditEvent(actor_id=user.id, action="scim.user.create", target=name, result="success"))
    db.commit()
    return JSONResponse(_scim_user(user), status_code=201)


@router.get("/Users/{uid}")
def get_user(uid: uuid.UUID, request: Request, db: DbSession, _auth=Depends(_auth)):
    user = db.get(m.User, uid)
    if not user:
        raise APIError("NOT_FOUND", "User not found", status=404)
    return _scim_user(user)


@router.patch("/Users/{uid}")
async def patch_user(uid: uuid.UUID, request: Request, db: DbSession, _auth=Depends(_auth)):
    user = db.get(m.User, uid)
    if not user:
        raise APIError("NOT_FOUND", "User not found", status=404)
    body = await request.json()
    active = body.get("active")
    if active is not None:
        user.status = m.USER_ACTIVE if active else m.USER_DISABLED
        if not active:
            for sess in db.query(m.AuthSession).filter_by(user_id=uid, revoked_at=None):
                sess.revoked_at = datetime.now(timezone.utc)
    if body.get("displayName"):
        user.display_name = str(body["displayName"])
    db.add(m.AuditEvent(actor_id=user.id, action="scim.user.patch", target=user.login_norm, result="success"))
    db.commit()
    return _scim_user(user)


@router.delete("/Users/{uid}", status_code=204)
def delete_user(uid: uuid.UUID, request: Request, db: DbSession, _auth=Depends(_auth)):
    user = db.get(m.User, uid)
    if not user:
        raise APIError("NOT_FOUND", "User not found", status=404)
    user.status = m.USER_DISABLED
    for sess in db.query(m.AuthSession).filter_by(user_id=uid, revoked_at=None):
        sess.revoked_at = datetime.now(timezone.utc)
    db.add(m.AuditEvent(actor_id=user.id, action="scim.user.delete", target=user.login_norm, result="success"))
    db.commit()
    return JSONResponse(status_code=204, content=None)
