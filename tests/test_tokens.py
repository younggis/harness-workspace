"""Scoped API token lifecycle tests."""
import uuid
from datetime import datetime, timedelta, timezone

from conftest import login, seed_world
from harness_common import models as m
from harness_common.security import new_token, token_hash


def test_token_create_list_revoke(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    r = client.post("/api/me/tokens", json={
        "name": "ci", "scopes": ["scim:write", "user:read"], "expires_in_days": 7,
    }, headers=hdr)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"] and body["scopes"] == ["scim:write", "user:read"]
    tid = body["id"]

    listed = client.get("/api/me/tokens", headers=hdr)
    assert listed.status_code == 200
    assert any(t["id"] == tid for t in listed.json()["items"])
    assert all("token" not in t for t in listed.json()["items"])

    assert client.delete(f"/api/me/tokens/{tid}", headers=hdr).status_code == 200
    with app.state.session_factory() as db:
        assert db.get(m.ApiToken, uuid.UUID(tid)).revoked_at is not None


def test_token_rejects_unknown_scope(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    r = client.post("/api/me/tokens", json={"name": "x", "scopes": ["bogus:scope"]}, headers=hdr)
    assert r.status_code == 409


def test_scim_accepts_scoped_api_token(tmp_path):
    from fastapi.testclient import TestClient
    from harness_common.config import Settings
    from harness_common.db import make_engine, make_session_factory
    from services.api.app.main import create_app

    settings = Settings(
        sqlite_path=f"sqlite:///{tmp_path / 't.db'}", pg_schema="main",
        portal_origin="http://portal.localhost:8080", workspace_host_suffix=".localhost:8080",
        relay_signing_key="k", session_signing_key="k", scim_bearer_token="static-token",
    )
    application = create_app(settings)
    eng = make_engine(settings.sqlite_path)
    m.Base.metadata.create_all(eng)
    application.state.engine = eng
    application.state.session_factory = make_session_factory(eng)
    raw = new_token(32)
    with application.state.session_factory() as db:
        uid = uuid.uuid4()
        db.add(m.User(id=uid, login_norm="svc", display_name="svc",
                      password_hash=token_hash(new_token()), is_platform_admin=False))
        db.flush()
        db.add(m.ApiToken(id=uuid.uuid4(), user_id=uid, name="scim", token_hash=token_hash(raw),
                          scopes="scim:write", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        db.commit()
    c = TestClient(application, raise_server_exceptions=True, follow_redirects=False)
    assert c.get("/scim/v2/Users", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    assert c.get("/scim/v2/Users", headers={"Authorization": "Bearer bad"}).status_code == 401
