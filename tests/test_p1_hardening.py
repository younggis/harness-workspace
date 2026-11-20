"""P1 hardening: CSRF header-only, API-token scopes, password policy, key rotation."""
import uuid

from conftest import login, seed_world
from harness_common import models as m
from harness_common.security import new_token, token_hash
from services.api.app import auth_oidc


def test_csrf_cookie_alone_is_rejected(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    # The CSRF cookie is still sent by TestClient, but the header is removed.
    only_cookie = {k: v for k, v in hdr.items() if k != "X-CSRF-Token"}
    r = client.post("/api/auth/active-tenant", json={"tenant_id": str(uuid.uuid4())},
                    headers=only_cookie)
    assert r.status_code == 403


def test_api_token_scope_enforced_on_admin_endpoints(client, app):
    w = seed_world(app)
    adm, _ = login(client, "p")
    r = client.post("/api/me/tokens", json={
        "name": "reader", "scopes": ["user:read"], "expires_in_days": 7,
    }, headers=adm)
    assert r.status_code == 201, r.text
    raw = r.json()["token"]

    # Bearer token works without CSRF and is limited to the granted scope.
    assert client.get("/api/admin/users",
                      headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    assert client.get("/api/admin/audit",
                      headers={"Authorization": f"Bearer {raw}"}).status_code == 403
    assert client.get("/api/admin/tenants",
                      headers={"Authorization": f"Bearer {raw}"}).status_code == 403


def test_api_token_with_matching_scope_and_last_used(client, app):
    seed_world(app)
    adm, _ = login(client, "p")
    r = client.post("/api/me/tokens", json={
        "name": "auditor", "scopes": ["audit:read", "tenant:read"], "expires_in_days": 7,
    }, headers=adm)
    raw = r.json()["token"]
    assert client.get("/api/admin/audit",
                      headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    assert client.get("/api/admin/tenants",
                      headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    with app.state.session_factory() as db:
        tok = db.query(m.ApiToken).filter_by(token_hash=token_hash(raw)).one()
        assert tok.last_used_at is not None


def test_revoked_api_token_rejected(client, app):
    seed_world(app)
    adm, _ = login(client, "p")
    r = client.post("/api/me/tokens", json={
        "name": "x", "scopes": ["user:read"], "expires_in_days": 7,
    }, headers=adm)
    body = r.json()
    assert client.delete(f"/api/me/tokens/{body['id']}", headers=adm).status_code == 200
    assert client.get("/api/admin/users",
                      headers={"Authorization": f"Bearer {body['token']}"}).status_code == 401


def test_password_policy(client, app):
    seed_world(app)
    hdr, _ = login(client, "p")
    weak = ("password1234", "abcdefghijkl", "AAAAAAAAAAAA")
    for pw in weak:
        r = client.post("/api/admin/users", json={
            "login": "weak" + uuid.uuid4().hex[:6], "display_name": "W", "password": pw,
        }, headers=hdr)
        assert r.status_code == 409, (pw, r.text)
    # Login name embedded in password is rejected.
    r = client.post("/api/admin/users", json={
        "login": "alice", "display_name": "A", "password": "Alice!passw0rd",
    }, headers=hdr)
    assert r.status_code == 409


def test_state_signature_key_rotation():
    from harness_common.config import Settings
    old, new = "old-key", "new-key"
    settings = Settings(session_signing_key=new, session_signing_key_previous=old)
    signed_old = auth_oidc.sign_state("state:nonce:verifier", old)
    signed_new = auth_oidc.sign_state("state:nonce:verifier", new)
    assert auth_oidc.verify_state_rotated(signed_old, settings) == "state:nonce:verifier"
    assert auth_oidc.verify_state_rotated(signed_new, settings) == "state:nonce:verifier"
    settings2 = Settings(session_signing_key=new)
    assert auth_oidc.verify_state_rotated(signed_old, settings2) is None
