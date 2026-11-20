"""/api/me exposes membership role so the portal can gate the admin menu."""
from conftest import login, seed_world


def test_me_returns_role_per_tenant(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", active_tenant=w["tA"])
    r = client.get("/api/me", headers=hdr)
    assert r.status_code == 200, r.text
    body = r.json()
    roles = {t["slug"]: t["role"] for t in body["tenants"]}
    assert roles == {"tenant-a": "tenant_admin"}


def test_me_role_for_multi_tenant_member(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    body = client.get("/api/me", headers=hdr).json()
    roles = {t["slug"]: t["role"] for t in body["tenants"]}
    assert roles == {"tenant-a": "member", "tenant-b": "member"}
    assert all(t["role"] != "tenant_admin" for t in body["tenants"])
