"""Offline tests for toB admin operations: audit, user lifecycle, session revocation."""
import uuid
from datetime import datetime, timedelta, timezone

from conftest import login, seed_world
from harness_common import models as m
from harness_common.security import new_token, token_hash


def test_platform_audit_lists_events(client, app):
    seed_world(app)
    hdr, _ = login(client, "p")
    r = client.get("/api/admin/audit", headers=hdr)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_user_disable_revokes_sessions_and_memberships(client, app):
    w = seed_world(app)
    with app.state.session_factory() as db:
        for uid in (w["A1"], w["TA"]):
            db.add(m.AuthSession(
                id=uuid.uuid4(), token_hash=token_hash(new_token()), user_id=uid,
                active_tenant_id=w["tA"], csrf_hash=token_hash(new_token()),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ))
        db.commit()
    hdr, _ = login(client, "p")
    r = client.patch(f"/api/admin/users/{w['A1']}", json={"status": "disabled"}, headers=hdr)
    assert r.status_code == 200
    with app.state.session_factory() as db:
        assert db.get(m.User, w["A1"]).status == "disabled"
        sessions = db.query(m.AuthSession).filter_by(user_id=w["A1"]).all()
        assert all(s.revoked_at is not None for s in sessions)
        ms = db.get(m.Membership, (w["tA"], w["A1"]))
        assert ms.status == "disabled"


def test_session_list_and_revoke(client, app):
    w = seed_world(app)
    with app.state.session_factory() as db:
        sid = uuid.uuid4()
        db.add(m.AuthSession(
            id=sid, token_hash=token_hash(new_token()), user_id=w["A1"],
            active_tenant_id=w["tA"], csrf_hash=token_hash(new_token()),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.commit()
    hdr, _ = login(client, "p")
    r = client.get(f"/api/admin/users/{w['A1']}/sessions", headers=hdr)
    assert r.status_code == 200 and len(r.json()["items"]) >= 1
    r = client.delete(f"/api/admin/sessions/{sid}", headers=hdr)
    assert r.status_code == 200 and r.json()["revoked"] is True
    with app.state.session_factory() as db:
        assert db.get(m.AuthSession, sid).revoked_at is not None
