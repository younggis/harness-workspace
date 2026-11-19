"""Offline tests for OIDC config discovery and TOTP MFA login flow."""
import pyotp

from conftest import login, seed_world


def test_oidc_config_disabled_by_default(client):
    r = client.get("/api/auth/oidc/config")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_mfa_enroll_verify_login_and_complete(client, app):
    seed_world(app)
    hdr, csrf = login(client, "a1")

    r = client.post("/api/auth/mfa/enroll", json={}, headers=hdr)
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    assert r.json()["enabled"] is False

    r = client.post("/api/auth/mfa/verify", json={"code": pyotp.TOTP(secret).now()}, headers=hdr)
    assert r.status_code == 200, r.text

    client.post("/api/auth/logout", headers=hdr)
    r = client.post("/api/auth/login", json={"login": "a1", "password": "Str0ngPassw0rd!x"},
                    headers={"Origin": "http://portal.localhost:8080"})
    assert r.status_code == 200
    assert r.json().get("mfa_required") is True
    assert client.cookies.get("harness_mfa")

    r = client.post("/api/auth/mfa/complete", json={"code": pyotp.TOTP(secret).now()},
                    headers={"Origin": "http://portal.localhost:8080"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["login_norm"] == "a1"
    assert r.json()["csrf_token"]

    me = client.get("/api/me", headers={"Origin": "http://portal.localhost:8080"})
    assert me.status_code == 200


def test_mfa_wrong_code_rejected(client, app):
    seed_world(app)
    hdr, csrf = login(client, "a1")
    r = client.post("/api/auth/mfa/enroll", json={}, headers=hdr)
    assert r.status_code == 200
    r = client.post("/api/auth/mfa/verify", json={"code": "000000"}, headers=hdr)
    assert r.status_code == 403
