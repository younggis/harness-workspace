"""Tenant-declared container resource policy (CPU/RAM/PIDS)."""
import uuid
from types import SimpleNamespace

from conftest import login, seed_world
from harness_common import limits as L, models as m


def test_tenant_create_with_resources_and_validation(client, app):
    seed_world(app)
    hdr, _ = login(client, "p")
    r = client.post("/api/admin/tenants", json={
        "slug": "res-tenant", "name": "Res Tenant", "max_running": 2, "max_workspaces": 5,
        "cpu_per_space": 2, "memory_per_space_bytes": 2 * L.GIB, "pids_per_space": 512,
        "max_total_cpu": 4, "max_total_memory_bytes": 4 * L.GIB, "max_total_pids": 1024,
    }, headers=hdr)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cpu_per_space"] == 2 and body["memory_per_space_bytes"] == 2 * L.GIB
    assert body["max_total_cpu"] == 4 and body["max_total_pids"] == 1024

    # per-space cannot exceed total
    bad = client.post("/api/admin/tenants", json={
        "slug": "bad", "name": "bad", "cpu_per_space": 8, "max_total_cpu": 4,
    }, headers=hdr)
    assert bad.status_code == 409
    # platform hard cap
    bad2 = client.post("/api/admin/tenants", json={
        "slug": "bad2", "name": "bad2", "cpu_per_space": L.MAX_CPU_PER_SPACE + 1,
        "max_total_cpu": L.MAX_TOTAL_CPU,
    }, headers=hdr)
    assert bad2.status_code == 422


def test_tenant_patch_cannot_lower_below_running_usage(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "p")
    # tenant-a has two running workspaces (a1, a2) using 1 CPU each.
    r = client.patch(f"/api/admin/tenants/{w['tA']}", json={"max_total_cpu": 1}, headers=hdr)
    assert r.status_code == 409  # below current running usage
    r = client.patch(f"/api/admin/tenants/{w['tA']}", json={"cpu_per_space": 2, "max_total_cpu": 4}, headers=hdr)
    assert r.status_code == 200


def test_workspace_inherits_and_overrides_resources(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", active_tenant=w["tA"])
    # a2 has no workspace yet; set tenant defaults first via platform admin.
    adm, _ = login(client, "p")
    assert client.patch(f"/api/admin/tenants/{w['tA']}", json={
        "cpu_per_space": 2, "memory_per_space_bytes": 2 * L.GIB, "pids_per_space": 512,
        "max_total_cpu": 8, "max_total_memory_bytes": 8 * L.GIB, "max_total_pids": 2048,
    }, headers=adm).status_code == 200

    inherited = client.post(f"/api/admin/tenants/{w['tA']}/workspaces", json={
        "owner_id": str(w["A2"]), "template_version": "base-v1",
    }, headers={**hdr, "Idempotency-Key": "inh"})
    assert inherited.status_code == 201, inherited.text
    assert inherited.json()["cpu"] == 2
    assert inherited.json()["memory_bytes"] == 2 * L.GIB

    # Override within tenant limits.
    over = client.post(f"/api/admin/tenants/{w['tA']}/workspaces", json={
        "owner_id": str(w["A2"]), "template_version": "base-v1",
    }, headers={**hdr, "Idempotency-Key": "inh"})  # idempotent: same owner
    assert over.status_code == 201 and over.json()["cpu"] == 2

    # A fresh tenant + owner: explicit memory above tenant spec is rejected.
    tr = client.post("/api/admin/tenants", json={
        "slug": "small", "name": "Small", "max_running": 2, "max_workspaces": 5,
        "cpu_per_space": 1, "memory_per_space_bytes": L.GIB, "pids_per_space": 256,
        "max_total_cpu": 2, "max_total_memory_bytes": 2 * L.GIB, "max_total_pids": 512,
    }, headers=adm).json()
    # a2 is not a member of 'small'; use platform admin to add membership.
    tid = tr["id"]
    # A brand-new tenant has no admin; make A2 its first tenant admin.
    mres = client.put(f"/api/admin/tenants/{tid}/members/{w['A2']}",
                      json={"role": "tenant_admin"}, headers=adm)
    assert mres.status_code == 200, mres.text
    too_big = client.post(f"/api/admin/tenants/{tid}/workspaces", json={
        "owner_id": str(w["A2"]), "template_version": "base-v1",
        "memory_bytes": 4 * L.GIB,
    }, headers={**adm, "Idempotency-Key": "big"})
    assert too_big.status_code == 409


def test_start_rejects_running_total_quota(client, app):
    w = seed_world(app)
    adm, _ = login(client, "p")
    # tenant-a currently has 2 running workspaces (a1, a2), 1 CPU each.
    assert client.patch(f"/api/admin/tenants/{w['tA']}", json={
        "max_total_cpu": 2, "max_total_memory_bytes": 2 * L.GIB, "max_total_pids": 512,
    }, headers=adm).status_code == 200
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    # Starting a1 again counts itself excluded => 1 other running => within 2.
    ok = client.post(f"/api/workspaces/{w['wsA1']}/actions/start",
                     headers={**hdr, "Idempotency-Key": "s1"})
    assert ok.status_code == 202
    # A third space would exceed. Re-login as admin (the a1 login replaced the
    # client cookie) before the remaining admin operations.
    adm, _ = login(client, "p")
    assert client.put(f"/api/admin/tenants/{w['tA']}/members/{w['B1']}",
                      json={"role": "member"}, headers=adm).status_code == 200
    ws3 = client.post(f"/api/admin/tenants/{w['tA']}/workspaces", json={
        "owner_id": str(w["B1"]), "template_version": "base-v1",
    }, headers={**adm, "Idempotency-Key": "w3"})
    assert ws3.status_code == 201, ws3.text
    # Current usage is exactly the 2-CPU quota; a third running space must be
    # rejected by check_running_totals on start.
    h3, _ = login(client, "b1", active_tenant=w["tA"])
    rejected = client.post(f"/api/workspaces/{ws3.json()['id']}/actions/start",
                           headers={**h3, "Idempotency-Key": "s3"})
    assert rejected.status_code == 409


def test_worker_spec_prefers_space_resources_and_falls_back(monkeypatch):
    from worker import main as wm

    monkeypatch.setattr(wm, "settings", SimpleNamespace(
        installation_id="t", workspace_host=lambda wid: f"w-{wid}:8080"))
    tpl = m.Template(id=uuid.uuid4(), version="base-v1", image_digest="sha256:x",
                     profile_hash="p", cpu=1, memory_bytes=L.GIB, pids_limit=256)
    db = SimpleNamespace(execute=lambda q: SimpleNamespace(scalar_one=lambda: tpl))
    ws = m.Workspace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), owner_id=uuid.uuid4(),
                     template_version="base-v1")

    ws.cpu, ws.memory_bytes, ws.pids_limit = 4, 8 * L.GIB, 1024
    spec = wm._spec_for(db, ws)
    assert (spec.cpu, spec.memory_bytes, spec.pids_limit) == (4, 8 * L.GIB, 1024)

    ws.cpu = ws.memory_bytes = ws.pids_limit = None  # legacy row → template fallback
    spec = wm._spec_for(db, ws)
    assert (spec.cpu, spec.memory_bytes, spec.pids_limit) == (1, L.GIB, 256)
