"""Self-service scoped API tokens (service accounts)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from sqlalchemy import select

from harness_common import models as m
from harness_common.errors import APIError
from harness_common.security import new_token, token_hash

from ..deps import CsrfDep, DbSession, IdentityDep
from ..permissions import Perm

router = APIRouter(prefix="/api/me/tokens")
ALLOWED_SCOPES = {p.value for p in Perm} | {"scim:write"}


@router.post("", status_code=201)
def create_token(body: dict, db: DbSession, identity: IdentityDep, _csrf: CsrfDep):
    name = str(body.get("name", "")).strip()
    scopes = body.get("scopes") or []
    days = int(body.get("expires_in_days", 30))
    if not name or not isinstance(scopes, list) or not scopes:
        raise APIError("CONFLICT", "name and scopes are required")
    unknown = [s for s in scopes if s not in ALLOWED_SCOPES]
    if unknown:
        raise APIError("CONFLICT", f"Unknown scopes: {unknown}")
    if days < 1 or days > 365:
        raise APIError("CONFLICT", "expires_in_days must be 1..365")

    raw = new_token(32)
    tok = m.ApiToken(
        id=uuid.uuid4(), user_id=identity.user.id, tenant_id=identity.tenant_id,
        name=name, token_hash=token_hash(raw), scopes=" ".join(scopes),
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
    )
    db.add(tok)
    db.add(m.AuditEvent(actor_id=identity.user.id, tenant_id=identity.tenant_id,
                        action="api_token.create", target=name, result="success"))
    db.commit()
    return {"id": str(tok.id), "name": name, "scopes": scopes,
            "expires_at": tok.expires_at.isoformat(), "token": raw}


@router.get("")
def list_tokens(db: DbSession, identity: IdentityDep):
    rows = db.execute(
        select(m.ApiToken).where(m.ApiToken.user_id == identity.user.id)
        .order_by(m.ApiToken.created_at.desc())
    ).scalars()
    return {"items": [{
        "id": str(t.id), "name": t.name, "scopes": t.scopes.split(),
        "expires_at": t.expires_at.isoformat(),
        "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
    } for t in rows]}


@router.delete("/{tid}")
def revoke_token(tid: uuid.UUID, db: DbSession, identity: IdentityDep, _csrf: CsrfDep):
    tok = db.get(m.ApiToken, tid)
    if not tok or tok.user_id != identity.user.id:
        raise APIError("NOT_FOUND", "Token not found")
    tok.revoked_at = datetime.now(timezone.utc)
    db.add(m.AuditEvent(actor_id=identity.user.id, action="api_token.revoke",
                        target=tok.name, result="success"))
    db.commit()
    return {"id": str(tid), "revoked": True}
