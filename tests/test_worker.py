"""Offline worker tests: lease claiming, idempotent processing, reconciliation."""
import uuid

from conftest import seed_world

from harness_common import models as m
from worker import main as wm
from worker.driver import RuntimeDriver, SpaceSpec


class FakeDriver(RuntimeDriver):
    def __init__(self):
        self.calls = []

    def start(self, spec): self.calls.append(("start", spec.generation)); return "cid"
    def stop(self, spec): self.calls.append(("stop", spec.generation))
    def rebuild(self, spec): self.calls.append(("rebuild", spec.generation)); return "cid2"
    def ensure(self, spec): self.calls.append(("ensure", spec.generation))
    def attach_gateway(self, spec): self.calls.append(("attach", spec.generation))
    def credential(self, spec): return "fake-model-token"


def test_claim_and_process_start(app):
    w = seed_world(app)
    wm.factory = app.state.session_factory
    drv = FakeDriver()
    with app.state.session_factory() as db:
        op = m.WorkspaceOperation(
            id=uuid.uuid4(), workspace_id=w["wsA2"], actor_id=w["TA"],
            op=m.OP_START, idempotency_key="t-start", request_hash="h",
            state=m.OP_QUEUED, target_generation=1,
        )
        db.add(op); db.commit(); oid = op.id
    with app.state.session_factory() as db:
        claimed = wm._claim_one(db)
        assert claimed is not None and claimed.id == oid
        assert claimed.state == m.OP_RUNNING and claimed.lease_owner
    wm.process(claimed, drv)
    with app.state.session_factory() as db:
        op = db.get(m.WorkspaceOperation, oid)
        ws = db.get(m.Workspace, w["wsA2"])
        creds = db.query(m.RuntimeCredential).filter_by(workspace_id=w["wsA2"]).all()
        assert op.state == m.OP_SUCCEEDED
        assert ws.observed_state == m.OBS_RUNNING
        assert len(creds) == 1 and creds[0].generation == 1
    assert ("start", 1) in drv.calls


def test_disabled_workspace_start_is_a_noop(app):
    w = seed_world(app)
    wm.factory = app.state.session_factory
    with app.state.session_factory() as db:
        db.get(m.Workspace, w["wsA1"]).enabled = False
        op = m.WorkspaceOperation(
            id=uuid.uuid4(), workspace_id=w["wsA1"], actor_id=w["TA"],
            op=m.OP_START, idempotency_key="t-disabled", request_hash="h",
            state=m.OP_QUEUED,
        )
        db.add(op); db.commit(); oid = op.id
        claimed = wm._claim_one(db)
        assert claimed is not None
    wm.process(claimed, FakeDriver())
    with app.state.session_factory() as db:
        assert db.get(m.WorkspaceOperation, oid).state == m.OP_SUCCEEDED


def test_reconcile_enqueues_missing_start(app):
    w = seed_world(app)
    wm.factory = app.state.session_factory
    with app.state.session_factory() as db:
        ws = db.get(m.Workspace, w["wsA2"])
        ws.desired_state = m.DESIRED_RUNNING
        ws.observed_state = m.OBS_STOPPED
        db.commit()
    wm.reconcile(FakeDriver())
    with app.state.session_factory() as db:
        ops = db.query(m.WorkspaceOperation).filter_by(workspace_id=w["wsA2"]).all()
        assert any(o.op == m.OP_START and o.state == m.OP_QUEUED for o in ops)
