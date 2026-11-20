"""Extreme-condition / abnormal-input acceptance tests.

Covers authentication abuse, malformed input, cross-tenant isolation, session
revocation, and container-side file-service invariants. All run offline (SQLite)
except where the real file service is exercised against a temp directory.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from conftest import login, seed_world
from harness_common import models as m
from harness_common.errors import APIError
from harness_common.security import token_hash

ORIGIN = "http://portal.localhost:8080"


# --------------------------------------------------------------------------- #
# Authentication / session abuse
# --------------------------------------------------------------------------- #
def test_login_empty_and_oversized_fields(client):
    assert client.post("/api/auth/login", json={"login": "", "password": ""},
                       headers={"Origin": ORIGIN}).status_code == 422
    assert client.post("/api/auth/login", json={"login": "a" * 300, "password": "x"},
                       headers={"Origin": ORIGIN}).status_code == 422
    assert client.post("/api/auth/login", json={"login": "a1", "password": "x" * 600},
                       headers={"Origin": ORIGIN}).status_code == 422


def test_login_malformed_json(client):
    r = client.post("/api/auth/login", content=b"{not json",
                    headers={"Origin": ORIGIN, "Content-Type": "application/json"})
    assert r.status_code == 422


def test_login_rate_limit_after_five_failures(client):
    name = "rl-" + uuid.uuid4().hex[:8]
    for _ in range(5):
        r = client.post("/api/auth/login", json={"login": name, "password": "bad"},
                        headers={"Origin": ORIGIN})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"login": name, "password": "bad"},
                    headers={"Origin": ORIGIN})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_no_and_garbage_session_cookie(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", cookies={"harness_session": "garbage"}).status_code == 401
    assert client.get("/api/me", cookies={"harness_session": "a" * 200}).status_code == 401


def test_expired_and_revoked_sessions(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    token = client.cookies.get("harness_session")
    with app.state.session_factory() as db:
        auth = db.query(m.AuthSession).filter_by(token_hash=token_hash(token)).one()
        auth.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/me", headers=hdr).status_code == 401

    # Fresh session, then revoke it.
    hdr, _ = login(client, "a1")
    token = client.cookies.get("harness_session")
    with app.state.session_factory() as db:
        db.query(m.AuthSession).filter_by(token_hash=token_hash(token)).one().revoked_at = datetime.now(timezone.utc)
        db.commit()
    assert client.get("/api/me", headers=hdr).status_code == 401


def test_disabled_user_cannot_use_session(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1")
    with app.state.session_factory() as db:
        db.get(m.User, w["A1"]).status = m.USER_DISABLED
        db.commit()
    assert client.get("/api/me", headers=hdr).status_code == 401


def test_invalid_csrf_on_write(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    bad = dict(hdr)
    bad["X-CSRF-Token"] = "wrong"
    r = client.post("/api/auth/active-tenant", json={"tenant_id": str(uuid.uuid4())}, headers=bad)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_switch_to_foreign_tenant_denied(client, app):
    # a2 belongs only to tenant-a; tenant-b must be rejected.
    w = seed_world(app)
    hdr, _ = login(client, "a2", active_tenant=w["tA"])
    r = client.post("/api/auth/active-tenant", json={"tenant_id": str(w["tB"])}, headers=hdr)
    assert r.status_code == 403


def test_revoked_membership_blocks_tenant(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    with app.state.session_factory() as db:
        ms = db.query(m.Membership).filter_by(user_id=w["A1"], tenant_id=w["tA"]).one()
        ms.status = m.MEMBER_DISABLED
        db.commit()
    assert client.get("/api/me", headers=hdr).status_code == 403


# --------------------------------------------------------------------------- #
# Malformed / injection inputs
# --------------------------------------------------------------------------- #
def test_invalid_uuid_and_unknown_action(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    assert client.get("/api/workspaces/not-a-uuid", headers=hdr).status_code == 422
    r = client.post(f"/api/workspaces/{uuid.uuid4()}/actions/rm-rf",
                    headers={**hdr, "Idempotency-Key": "edge-action"})
    assert r.status_code == 404


def test_admin_duplicate_user_and_tenant(client, app):
    seed_world(app)
    hdr, _ = login(client, "p")
    assert client.post("/api/admin/users", json={"login": "a1", "display_name": "dup", "password": "x" * 12},
                       headers=hdr).status_code == 409
    assert client.post("/api/admin/tenants", json={"slug": "tenant-a", "name": "dup"},
                       headers=hdr).status_code == 409


def test_mfa_invalid_and_unenrolled(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    assert client.post("/api/auth/mfa/verify", json={"code": "000000"}, headers=hdr).status_code == 409
    en = client.post("/api/auth/mfa/enroll", json={}, headers=hdr)
    assert en.status_code == 200 and en.json()["secret"]
    assert client.post("/api/auth/mfa/verify", json={"code": "000000"}, headers=hdr).status_code == 403


def test_scim_weird_username_and_duplicate(client, app):
    seed_world(app)
    # Settings is frozen; enable SCIM by replacing the app-level settings object.
    from dataclasses import replace
    app.state.settings = replace(app.state.settings, scim_bearer_token="t")
    h = {"Authorization": "Bearer t"}
    r = client.post("/scim/v2/Users", json={"userName": "  Weird.User+tag@x  ", "displayName": "W"}, headers=h)
    assert r.status_code == 201 and r.json()["userName"] == "weird.user+tag@x"
    assert client.post("/scim/v2/Users", json={"userName": "weird.user+tag@x"}, headers=h).status_code == 409
    assert client.post("/scim/v2/Users", json={"userName": ""}, headers=h).status_code == 409


def test_token_empty_scopes_and_bad_expiry(client, app):
    seed_world(app)
    hdr, _ = login(client, "a1")
    assert client.post("/api/me/tokens", json={"name": "x", "scopes": []}, headers=hdr).status_code == 409
    assert client.post("/api/me/tokens", json={"name": "x", "scopes": ["user:read"], "expires_in_days": 0},
                       headers=hdr).status_code == 409
    assert client.post("/api/me/tokens", json={"name": "x", "scopes": ["user:read"], "expires_in_days": 400},
                       headers=hdr).status_code == 409


# --------------------------------------------------------------------------- #
# Cross-tenant isolation
# --------------------------------------------------------------------------- #
def test_cross_tenant_workspace_invisible(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    assert client.get(f"/api/workspaces/{w['wsB1']}", headers=hdr).status_code == 404
    hdr2, _ = login(client, "b1", active_tenant=w["tB"])
    assert client.get(f"/api/workspaces/{w['wsA1']}", headers=hdr2).status_code == 404


def test_cross_tenant_member_list_denied(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    assert client.get(f"/api/admin/tenants/{w['tB']}/members", headers=hdr).status_code == 403


def test_entry_ticket_foreign_workspace_denied(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    r = client.post(f"/api/workspaces/{w['wsB1']}/entry-tickets",
                    json={"target": "agent"}, headers=hdr)
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
def test_idempotency_key_same_and_different_params(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    h1 = {**hdr, "Idempotency-Key": "idem-1"}
    a = client.post(f"/api/workspaces/{w['wsA1']}/actions/stop", headers=h1)
    b = client.post(f"/api/workspaces/{w['wsA1']}/actions/stop", headers=h1)
    assert a.status_code == 202 and b.status_code == 202
    assert a.json()["operation_id"] == b.json()["operation_id"]
    h2 = {**hdr, "Idempotency-Key": "idem-1"}
    c = client.post(f"/api/workspaces/{w['wsA1']}/actions/start", headers=h2)
    assert c.status_code == 409  # same key, different action
    assert client.post(f"/api/workspaces/{w['wsA1']}/actions/stop",
                       headers={**hdr}).status_code == 409  # missing key


# --------------------------------------------------------------------------- #
# Container-side file service invariants (real OS operations on a temp dir)
# --------------------------------------------------------------------------- #
@pytest.fixture
def fs(tmp_path):
    import runtime.base.fileservice as fs
    prev = fs.ROOT_FD
    fs.open_root(str(tmp_path))
    yield fs
    os.close(fs.ROOT_FD)
    fs.ROOT_FD = prev


# The path grammar is pure and portable; the OS-level dir_fd checks run only on Linux
# (the same code is exercised for real inside the runtime container by
# scripts/fileservice_probe.py).
@pytest.mark.parametrize("path", [
    "../secret", "a/../../secret", "/etc/passwd", "a\\b", "a\x00b", "", ".", "..",
])
def test_fileservice_path_grammar_rejects_bad_paths(path):
    import runtime.base.fileservice as fs
    with pytest.raises(ValueError):
        fs._components(path)


LINUX_ONLY = pytest.mark.skipif(not hasattr(os, "O_DIRECTORY"),
                                reason="dir_fd file service is Linux-only")


@LINUX_ONLY
def test_fileservice_symlink_and_nonregular_rejected(fs, tmp_path):
    fs.write_file("target.txt", b"data")
    os.symlink(os.path.join(str(tmp_path), "target.txt"), os.path.join(str(tmp_path), "link.txt"))
    with pytest.raises(ValueError):
        fs.read_file("link.txt")
    os.mkdir(os.path.join(str(tmp_path), "adir"))
    with pytest.raises(ValueError):
        fs.read_file("adir")


@LINUX_ONLY
def test_fileservice_etag_and_create_conflict(fs):
    etag = fs.write_file("f.txt", b"v1")
    assert fs.write_file("f.txt", b"v2", etag=etag)  # correct etag succeeds
    with pytest.raises(ValueError) as e:
        fs.write_file("f.txt", b"v3", etag="wrong")
    assert str(e.value) == "VERSION_CONFLICT"
    with pytest.raises(ValueError) as e:
        fs.write_file("f.txt", b"v4", create=True)
    assert str(e.value) == "ALREADY_EXISTS"


@LINUX_ONLY
def test_fileservice_oversize(fs, monkeypatch):
    monkeypatch.setattr(fs, "MAX_UPLOAD", 16)
    with pytest.raises(ValueError) as e:
        fs.write_file("big.bin", b"x" * 17)
    assert str(e.value) == "PAYLOAD_TOO_LARGE"


@LINUX_ONLY
def test_fileservice_nested_dirs_and_move(fs):
    fs.mkdir("sub")
    fs.write_file("sub/a.txt", b"a")
    assert fs.read_file("sub/a.txt")[0] == b"a"
    fs.move("sub/a.txt", "sub/b.txt")
    assert fs.read_file("sub/b.txt")[0] == b"a"
    assert sorted(x["name"] for x in fs.list_dir("sub")) == ["b.txt"]
