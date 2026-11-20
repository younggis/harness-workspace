"""P3: metrics exposition and audit CSV export."""
from conftest import login, seed_world
from harness_common.metrics import Metrics


def test_metrics_text_format():
    m = Metrics("harness_test_")
    m.inc("requests_total", {"status": 200})
    m.inc("requests_total", {"status": 200})
    m.set("active", 3)
    text = m.render()
    assert "# TYPE harness_test_requests_total counter" in text
    assert 'harness_test_requests_total{status="200"} 2' in text
    assert "# TYPE harness_test_active gauge" in text
    assert "harness_test_active 3" in text


def test_metrics_endpoint(client, app):
    client.get("/health/live")  # generate at least one counted request
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "harness_api_http_requests_total" in r.text


def test_metrics_record_requests_and_logins(client, app):
    seed_world(app)
    login(client, "p")  # one success
    client.post("/api/auth/login", json={"login": "p", "password": "wrong"},
                headers={"Origin": "http://portal.localhost:8080"})  # one failure
    text = client.get("/metrics").text
    assert 'harness_api_login_total{result="success"}' in text
    assert 'harness_api_login_total{result="failure"}' in text
    assert "harness_api_http_requests_total" in text


def test_audit_csv_export(client, app):
    seed_world(app)
    hdr, _ = login(client, "p")
    r = client.get("/api/admin/audit/export?limit=100", headers=hdr)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    lines = r.text.strip().splitlines()
    assert lines[0] == "occurred_at,actor_id,tenant_id,workspace_id,action,target,result,request_id"
    assert len(lines) > 1  # seeded world has audit events


def test_audit_export_requires_permission(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "a1", active_tenant=w["tA"])
    assert client.get("/api/admin/audit/export", headers=hdr).status_code == 403
