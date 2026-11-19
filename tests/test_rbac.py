"""Fine-grained RBAC enforcement tests."""
from conftest import login, seed_world


def test_tenant_admin_has_member_permissions(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", active_tenant=w["tA"])
    r = client.get(f"/api/admin/tenants/{w['tA']}/members", headers=hdr)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/admin/tenants/{w['tA']}/workspaces", headers=hdr)
    assert r.status_code == 200, r.text


def test_member_lacks_admin_permissions(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    assert client.get("/api/admin/users", headers=hdr).status_code == 403
    assert client.get(f"/api/admin/tenants/{w['tA']}/audit", headers=hdr).status_code == 403
    assert client.get(f"/api/admin/tenants/{w['tA']}/usage", headers=hdr).status_code == 403


def test_platform_admin_has_all_permissions(client, app):
    seed_world(app)
    hdr, _ = login(client, "p")
    assert client.get("/api/admin/users", headers=hdr).status_code == 200
    assert client.get("/api/admin/audit", headers=hdr).status_code == 200
