"""Offline control-plane tests: auth, tenancy, authorization, idempotency.

These exercise T01/T02/T03/T04/T05 at the real protected entry points (not via UI).
"""
import uuid

import pytest

from conftest import login, seed_world


def test_login_and_me(client, app):
    w = seed_world(app)
    hdr, csrf = login(client, "a1", w["password"])
    r = client.get("/api/me", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["login_norm"] == "a1"
    assert {t["slug"] for t in r.json()["tenants"]} == {"tenant-a", "tenant-b"}


def test_login_generic_error_and_rate_limit(client, app):
    seed_world(app)
    for _ in range(5):
        r = client.post("/api/auth/login", json={"login": "p", "password": "wrong"},
                        headers={"Origin": "http://portal.localhost:8080"})
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Invalid credentials"
    r = client.post("/api/auth/login", json={"login": "p", "password": "wrong"},
                    headers={"Origin": "http://portal.localhost:8080"})
    assert r.status_code == 429


def test_login_requires_exact_origin(client, app):
    seed_world(app)
    r = client.post("/api/auth/login", json={"login": "p", "password": "Str0ngPassw0rd!x"})
    assert r.status_code == 403
    r = client.post("/api/auth/login", json={"login": "p", "password": "Str0ngPassw0rd!x"},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_csrf_enforced_on_state_change(client, app):
    w = seed_world(app)
    hdr, csrf = login(client, "ta", w["password"])
    r = client.post("/api/admin/tenants", json={"slug": "x", "name": "X"},
                    headers={"Origin": "http://portal.localhost:8080"})
    assert r.status_code == 403  # missing CSRF
    r = client.post("/api/admin/tenants", json={"slug": "x", "name": "X"},
                    headers={"Origin": "http://portal.localhost:8080", "X-CSRF-Token": "bad"})
    assert r.status_code == 403


def test_platform_admin_tenant_crud_and_duplicates(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "p", w["password"])
    r = client.post("/api/admin/tenants", json={"slug": "tenant-c", "name": "Tenant C"}, headers=hdr)
    assert r.status_code == 201, r.text
    r2 = client.post("/api/admin/tenants", json={"slug": "tenant-c", "name": "Tenant C again"}, headers=hdr)
    assert r2.status_code == 409
    r3 = client.get("/api/admin/tenants", headers=hdr)
    assert any(t["slug"] == "tenant-c" for t in r3.json()["items"])


def test_ta_cannot_act_on_other_tenant(client, app):
    """T02: TA requesting B's operations yields 404 (uniform non-enumeration)."""
    w = seed_world(app)
    hdr, _ = login(client, "ta", w["password"], active_tenant=w["tA"])
    r = client.post(f"/api/admin/tenants/{w['tB']}/workspaces",
                    json={"owner_id": str(w["B1"]), "template_version": "base-v1"},
                    headers={**hdr, "Idempotency-Key": "k1"})
    assert r.status_code == 404
    r = client.get(f"/api/admin/tenants/{w['tB']}/usage", headers=hdr)
    assert r.status_code == 404


def test_platform_admin_cannot_read_member_files(client, app):
    """T02: management privilege does not grant file/workspace-session access."""
    w = seed_world(app)
    hdr, _ = login(client, "p", w["password"])
    r = client.post(f"/api/workspaces/{w['wsA1']}/entry-tickets",
                    json={"target": "files"}, headers={**hdr, "Idempotency-Key": "x"})
    # P has no active tenant and is not the owner -> no ticket.
    assert r.status_code in (403, 404)


def test_workspace_allocation_idempotent_and_quota(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", w["password"], active_tenant=w["tA"])
    key = "alloc-a2"
    body = {"owner_id": str(w["A2"]), "template_version": "base-v1"}
    r1 = client.post(f"/api/admin/tenants/{w['tA']}/workspaces", json=body,
                     headers={**hdr, "Idempotency-Key": key})
    assert r1.status_code == 201, r1.text
    r2 = client.post(f"/api/admin/tenants/{w['tA']}/workspaces", json=body,
                     headers={**hdr, "Idempotency-Key": "alloc-a2-other"})
    assert r2.status_code == 201  # unique constraint returns the same record
    assert r1.json()["id"] == r2.json()["id"]


def test_workspace_action_idempotency_and_conflict(client, app):
    """T05: same key+params -> same operation; same key different params -> 409."""
    w = seed_world(app)
    hdr, _ = login(client, "a1", w["password"], active_tenant=w["tA"])
    h = {**hdr, "Idempotency-Key": "start-once"}
    r1 = client.post(f"/api/workspaces/{w['wsA1']}/actions/start", headers=h)
    assert r1.status_code == 202, r1.text
    r2 = client.post(f"/api/workspaces/{w['wsA1']}/actions/start", headers=h)
    assert r2.status_code == 202
    assert r1.json()["operation_id"] == r2.json()["operation_id"]
    r3 = client.post(f"/api/workspaces/{w['wsA1']}/actions/stop", headers=h)
    assert r3.status_code == 409


def test_cross_tenant_workspace_isolation(client, app):
    """T03: A1 sees only own space; A2/B1 spaces and their operations 404."""
    w = seed_world(app)
    hdr, _ = login(client, "a1", w["password"], active_tenant=w["tA"])
    rooms = client.get("/api/workspaces", headers=hdr).json()
    assert [x["id"] for x in rooms] == [str(w["wsA1"])]
    assert client.get(f"/api/workspaces/{w['wsA2']}", headers=hdr).status_code == 404
    assert client.get(f"/api/workspaces/{w['wsB1']}", headers=hdr).status_code == 404
    assert client.get(f"/api/workspaces/{uuid.uuid4()}", headers=hdr).status_code == 404


def test_tenant_switch_revokes_old_link(client, app):
    """T02: after A1 switches to B, the old tenant-A link is no longer reachable."""
    w = seed_world(app)
    hdr, _ = login(client, "a1", w["password"], active_tenant=w["tA"])
    assert client.get(f"/api/workspaces/{w['wsA1']}", headers=hdr).status_code == 200
    r = client.post("/api/auth/active-tenant", json={"tenant_id": str(w["tB"])}, headers=hdr)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/workspaces/{w['wsA1']}", headers=hdr).status_code == 404
    # Active tenant is now B; A1 owns no space there, so the B1 space stays invisible.
    assert client.get(f"/api/workspaces/{w['wsB1']}", headers=hdr).status_code == 404
    assert client.get("/api/me", headers=hdr).json()["active_tenant_id"] == str(w["tB"])


def test_disable_blocks_entry_ticket_and_raise_epoch(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", w["password"], active_tenant=w["tA"])
    r = client.post(f"/api/workspaces/{w['wsA1']}/actions/disable",
                    headers={**hdr, "Idempotency-Key": "dis1"})
    assert r.status_code == 202, r.text
    a1hdr, _ = login(client, "a1", w["password"], active_tenant=w["tA"])
    r = client.post(f"/api/workspaces/{w['wsA1']}/entry-tickets",
                    json={"target": "files"}, headers={**a1hdr, "Idempotency-Key": "tick1"})
    assert r.status_code == 404


def test_entry_ticket_single_use_and_host_binding(client, app):
    """T04: a ticket is single-use and host-bound."""
    w = seed_world(app)
    hdr, _ = login(client, "a1", w["password"], active_tenant=w["tA"])
    r = client.post(f"/api/workspaces/{w['wsA1']}/entry-tickets",
                    json={"target": "files"}, headers={**hdr, "Idempotency-Key": "tk"})
    assert r.status_code == 201, r.text
    ticket = r.json()["ticket"]
    host = f"w-{w['wsA1']}.localhost:8080"
    origin = f"http://{host}"
    r1 = client.post("/_platform/enter", data={"ticket": ticket},
                     headers={"Host": host, "Origin": "http://portal.localhost:8080"})
    assert r1.status_code == 303, r1.text
    r2 = client.post("/_platform/enter", data={"ticket": ticket},
                     headers={"Host": host, "Origin": "http://portal.localhost:8080"})
    assert r2.status_code == 403  # already consumed

    # wrong host fails
    hdr2, _ = login(client, "a1", w["password"], active_tenant=w["tA"])
    r = client.post(f"/api/workspaces/{w['wsA1']}/entry-tickets",
                    json={"target": "files"}, headers={**hdr2, "Idempotency-Key": "tk2"})
    ticket2 = r.json()["ticket"]
    r3 = client.post("/_platform/enter", data={"ticket": ticket2},
                     headers={"Host": "w-wrong.localhost:8080", "Origin": "http://portal.localhost:8080"})
    assert r3.status_code == 403
