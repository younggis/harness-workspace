"""Test fixtures for offline unit/integration tests.

Offline tests use a per-test SQLite database in the `main` schema so the dedicated
PostgreSQL harness schema is never touched. Integration tests (marked `integration`)
use real Docker/PostgreSQL and are skipped unless explicitly enabled.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "common"), str(ROOT / "services" / "worker")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("HARNESS_SQLITE_PATH", "")  # tests override via create_app
os.environ.setdefault("RELAY_SIGNING_KEY", "test-relay-signing-key-not-a-secret")
os.environ.setdefault("SESSION_SIGNING_KEY", "test-session-key")

from harness_common import models as m  # noqa: E402
from harness_common.config import Settings  # noqa: E402
from harness_common.db import make_engine, make_session_factory  # noqa: E402
from harness_common.security import hash_password, new_token, token_hash  # noqa: E402


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    # The limiter now lives on app.state (per-test app instance), so counters
    # are naturally isolated. Yield kept for fixture API compatibility.
    yield


@pytest.fixture
def settings(tmp_path):
    return Settings(
        sqlite_path=f"sqlite:///{tmp_path / 'test.db'}",
        pg_schema="main",
        portal_origin="http://portal.localhost:8080",
        workspace_host_suffix=".localhost:8080",
        relay_signing_key="test-relay-key",
        session_signing_key="test-session-key",
        installation_id="test-install",
    )


@pytest.fixture
def app(settings):
    from services.api.app.main import create_app
    application = create_app(settings)
    eng = make_engine(settings.sqlite_path)
    m.Base.metadata.create_all(eng)
    application.state.session_factory = make_session_factory(eng)
    application.state.engine = eng
    return application


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=True, follow_redirects=False) as c:
        yield c


def seed_world(app):
    """Create P, TA, A1, A2, B1; tenants A and B; memberships; a running workspace for A1.

    Returns a dict of ids and plaintext passwords.
    """
    from datetime import timedelta
    from harness_common.security import new_token, token_hash

    factory = app.state.session_factory
    with factory() as db:
        def user(login, admin=False, pw="Str0ngPassw0rd!x"):
            u = m.User(id=uuid.uuid4(), login_norm=login, display_name=login.upper(),
                       password_hash=hash_password(pw), is_platform_admin=admin)
            db.add(u); db.flush()
            return u
        P = user("p", admin=True)
        TA = user("ta"); A1 = user("a1"); A2 = user("a2"); B1 = user("b1")
        tA = m.Tenant(id=uuid.uuid4(), slug="tenant-a", name="Tenant A",
                      max_running=4, max_workspaces=10)
        tB = m.Tenant(id=uuid.uuid4(), slug="tenant-b", name="Tenant B",
                      max_running=2, max_workspaces=5)
        db.add_all([tA, tB]); db.flush()
        for u, t, role in [(TA, tA, m.MEMBER_ADMIN), (A1, tA, m.MEMBER_MEMBER),
                           (A2, tA, m.MEMBER_MEMBER), (B1, tB, m.MEMBER_MEMBER),
                           (A1, tB, m.MEMBER_MEMBER)]:
            db.add(m.Membership(tenant_id=t.id, user_id=u.id, role=role))
        tpl = m.Template(id=uuid.uuid4(), version="base-v1", image_digest="sha256:abc123",
                         profile_hash="prof1", cpu=1, memory_bytes=1073741824, pids_limit=256)
        db.add(tpl); db.flush()
        wsA1 = m.Workspace(id=uuid.uuid4(), tenant_id=tA.id, owner_id=A1.id,
                           template_version="base-v1", observed_state=m.OBS_RUNNING,
                           desired_state=m.DESIRED_RUNNING, generation=1)
        wsA2 = m.Workspace(id=uuid.uuid4(), tenant_id=tA.id, owner_id=A2.id,
                           template_version="base-v1", observed_state=m.OBS_RUNNING,
                           desired_state=m.DESIRED_RUNNING, generation=1)
        wsB1 = m.Workspace(id=uuid.uuid4(), tenant_id=tB.id, owner_id=B1.id,
                           template_version="base-v1", observed_state=m.OBS_RUNNING,
                           desired_state=m.DESIRED_RUNNING, generation=1)
        db.add_all([wsA1, wsA2, wsB1]); db.commit()
        return {
            "P": P.id, "TA": TA.id, "A1": A1.id, "A2": A2.id, "B1": B1.id,
            "tA": tA.id, "tB": tB.id,
            "wsA1": wsA1.id, "wsA2": wsA2.id, "wsB1": wsB1.id,
            "password": "Str0ngPassw0rd!x",
        }


def login(client, login_name, password="Str0ngPassw0rd!x", active_tenant=None):
    r = client.post("/api/auth/login", json={"login": login_name, "password": password},
                    headers={"Origin": "http://portal.localhost:8080"})
    assert r.status_code == 200, r.text
    csrf = r.json()["csrf_token"]
    cookies = {"harness_session": client.cookies.get("harness_session")}
    if active_tenant:
        r2 = client.post("/api/auth/active-tenant", json={"tenant_id": str(active_tenant)},
                         headers={"Origin": "http://portal.localhost:8080",
                                  "X-CSRF-Token": csrf})
        assert r2.status_code == 200, r2.text
        csrf = r2.json()["csrf_token"]
    return {"X-CSRF-Token": csrf, "Origin": "http://portal.localhost:8080"}, csrf
