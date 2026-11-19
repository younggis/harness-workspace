"""Offline SCIM 2.0 provisioning tests with a fake bearer token."""
from fastapi.testclient import TestClient

from harness_common import models as m
from harness_common.config import Settings
from harness_common.db import make_engine, make_session_factory
from services.api.app.main import create_app


def _client(tmp_path):
    settings = Settings(
        sqlite_path=f"sqlite:///{tmp_path / 'scim.db'}",
        pg_schema="main", portal_origin="http://portal.localhost:8080",
        workspace_host_suffix=".localhost:8080", relay_signing_key="k",
        session_signing_key="k", scim_bearer_token="scim-secret",
    )
    app = create_app(settings)
    engine = make_engine(settings.sqlite_path)
    m.Base.metadata.create_all(engine)
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    return TestClient(app, raise_server_exceptions=True, follow_redirects=False)


def test_scim_requires_bearer(tmp_path):
    c = _client(tmp_path)
    assert c.get("/scim/v2/Users").status_code == 401
    assert c.get("/scim/v2/Users", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/scim/v2/Users", headers={"Authorization": "Bearer scim-secret"}).status_code == 200


def test_scim_user_lifecycle(tmp_path):
    c = _client(tmp_path)
    h = {"Authorization": "Bearer scim-secret"}
    r = c.post("/scim/v2/Users", json={"userName": "scimuser", "displayName": "SCIM User"}, headers=h)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["active"] is True
    assert c.get(f"/scim/v2/Users/{uid}", headers=h).status_code == 200
    r = c.patch(f"/scim/v2/Users/{uid}", json={"active": False}, headers=h)
    assert r.status_code == 200 and r.json()["active"] is False
    r = c.get("/scim/v2/Users?filter=userName eq \"scimuser\"", headers=h)
    assert r.status_code == 200 and len(r.json()["Resources"]) >= 1
    assert c.delete(f"/scim/v2/Users/{uid}", headers=h).status_code == 204
