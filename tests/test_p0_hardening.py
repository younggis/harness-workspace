"""P0 hardening: shared start quotas, generation atomicity, distributed
login limiter, and automatic orphan-network GC."""
import uuid

from conftest import login, seed_world
from harness_common import models as m

from services.api.app.ratelimit import LoginRateLimiter


class RecordingDriver:
    def __init__(self):
        self.calls = []
    def ensure(self, spec): self.calls.append("ensure")
    def start(self, spec): self.calls.append("start"); return "cid"
    def stop(self, spec): self.calls.append("stop")
    def rebuild(self, a, b): self.calls.append("rebuild"); return "cid"
    def attach_gateway(self, spec): self.calls.append("attach")
    def credential(self, spec): return "token"


def test_worker_enforces_start_quota(client, app):
    from worker import main as wm
    w = seed_world(app)
    wm.factory = app.state.session_factory
    adm, _ = login(client, "p")
    # tenant-a already has two running spaces; cap it at one.
    assert client.patch(f"/api/admin/tenants/{w['tA']}",
                        json={"max_running": 1}, headers=adm).status_code == 200
    with app.state.session_factory() as db:
        op = m.WorkspaceOperation(
            id=uuid.uuid4(), workspace_id=w["wsA1"], actor_id=w["A1"],
            op=m.OP_START, idempotency_key="worker-quota", request_hash="h",
            state=m.OP_QUEUED, target_generation=1,
        )
        db.add(op); db.commit(); oid = op.id
    drv = RecordingDriver()
    wm.process(op, drv)
    with app.state.session_factory() as db:
        assert db.get(m.WorkspaceOperation, oid).state == m.OP_FAILED
    assert "start" not in drv.calls  # container was never created


def test_rapid_second_action_returns_409_not_500(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", active_tenant=w["tA"])
    first = client.post(f"/api/workspaces/{w['wsA1']}/actions/stop",
                        headers={**hdr, "Idempotency-Key": "first"})
    assert first.status_code == 202
    second = client.post(f"/api/workspaces/{w['wsA1']}/actions/start",
                         headers={**hdr, "Idempotency-Key": "second"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


def test_api_rebuild_does_not_advance_generation(client, app):
    w = seed_world(app)
    hdr, _ = login(client, "ta", active_tenant=w["tA"])
    with app.state.session_factory() as db:
        before = db.get(m.Workspace, w["wsA1"]).generation
    r = client.post(f"/api/workspaces/{w['wsA1']}/actions/rebuild",
                    headers={**hdr, "Idempotency-Key": "rb"})
    assert r.status_code == 202, r.text
    with app.state.session_factory() as db:
        ws = db.get(m.Workspace, w["wsA1"])
        assert ws.generation == before  # worker advances it only on success
        assert r.json()["op"] == "rebuild"


def test_local_login_limiter_lifecycle():
    lim = LoginRateLimiter(redis_url="")
    assert lim.backend == "local"
    for _ in range(5):
        assert lim.allowed("u")
        lim.record_failure("u")
    assert not lim.allowed("u")
    lim.clear("u")
    assert lim.allowed("u")


class _FakePipeline:
    def __init__(self, owner):
        self.owner = owner
        self.results = []
    def zremrangebyscore(self, key, _min, _max):
        self.owner.data[key] = [x for x in self.owner.data.get(key, []) if x >= _max]
        self.results.append(None); return self
    def zcard(self, key):
        self.results.append(len(self.owner.data.get(key, []))); return self
    def expire(self, key, ttl):
        self.results.append(True); return self
    def zadd(self, key, mapping):
        self.owner.data.setdefault(key, []).extend(mapping.values()); return self
    def execute(self):
        out = self.results[:]; self.results = []; return out


class _FakeRedis:
    def __init__(self):
        self.data = {}
    def pipeline(self):
        return _FakePipeline(self)
    def delete(self, key):
        self.data.pop(key, None)


def test_redis_login_limiter_shared_state():
    a = LoginRateLimiter(redis_url="")
    b = LoginRateLimiter(redis_url="")
    fake = _FakeRedis()
    a._redis = fake
    b._redis = fake
    assert a.backend == b.backend == "redis"
    for _ in range(5):
        assert a.allowed("u")
        a.record_failure("u")
    # A different API replica sees the same failures.
    assert not b.allowed("u")
    b.clear("u")
    assert a.allowed("u")


def test_gc_networks_removes_only_orphans():
    from worker.driver import DockerRuntimeDriver

    class FakeNet:
        def __init__(self, name, endpoints):
            self.name = name
            self.attrs = {"Containers": {
                k: {"Name": v} for k, v in endpoints.items()
            }}
            self.removed = False
        def reload(self): pass
        def disconnect(self, endpoint, force=False): pass
        def remove(self):
            self.removed = True
    cur = "aaaaaaaa-0000-0000-0000-000000000001"
    old = "bbbbbbbb-0000-0000-0000-000000000002"
    dis = "cccccccc-0000-0000-0000-000000000003"
    nets = [
        FakeNet(f"harness-i-net-{cur}-g1", {"c": f"harness-i-rt-{cur}-g1"}),
        FakeNet(f"harness-i-net-{old}-g0", {"e": "harness-i-relay-1"}),
        FakeNet(f"harness-i-net-{dis}-g3", {"e": "harness-i-relay-1"}),
    ]
    class FakeClient:
        class networks:
            @staticmethod
            def list(filters): return nets
    drv = object.__new__(DockerRuntimeDriver)
    drv.installation_id = "i"
    drv.client = FakeClient()
    removed = drv.gc_networks({
        f"harness-i-net-{cur}-g1",
        f"harness-i-net-{dis}-g3",
    })
    assert removed == 1
    assert nets[1].removed and not nets[0].removed and not nets[2].removed
