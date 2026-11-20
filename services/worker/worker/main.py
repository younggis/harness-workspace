"""Operation queue consumer and resource reconciler."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from harness_common import models as m
from harness_common.config import get_settings
from harness_common.db import make_engine, make_session_factory
from harness_common.security import token_hash

from .driver import DockerRuntimeDriver, SpaceSpec, RuntimeDriver

settings = get_settings()
engine = make_engine(settings.app_database_url(), schema=settings.pg_schema)
factory = make_session_factory(engine)
WORKER_ID = os.environ.get("WORKER_ID", f"worker-{uuid.uuid4().hex[:8]}")
LEASE_SECONDS = 120


def _claim_one(db):
    now = datetime.now(timezone.utc)
    q = db.query(m.WorkspaceOperation).filter(
        (m.WorkspaceOperation.state == m.OP_QUEUED) |
        ((m.WorkspaceOperation.state == m.OP_RUNNING) & (m.WorkspaceOperation.lease_until < now))
    ).order_by(m.WorkspaceOperation.created_at)
    if db.bind.dialect.name != "sqlite":
        q = q.with_for_update(skip_locked=True)
    op = q.first()
    if not op:
        return None
    op.state = m.OP_RUNNING
    op.lease_owner = WORKER_ID
    op.lease_until = now + timedelta(seconds=LEASE_SECONDS)
    op.attempt += 1
    db.commit()
    return op


def _spec_for(db, ws: m.Workspace) -> SpaceSpec:
    tpl = db.execute(
        __import__("sqlalchemy").select(m.Template).where(m.Template.version == ws.template_version)
    ).scalar_one()
    return SpaceSpec(
        workspace_id=str(ws.id), tenant_id=str(ws.tenant_id), generation=ws.generation,
        installation_id=settings.installation_id, image=tpl.image_digest,
        # Space-level resources (tenant policy) win; legacy NULL rows still
        # inherit the immutable template values.
        cpu=ws.cpu if ws.cpu is not None else tpl.cpu,
        memory_bytes=ws.memory_bytes if ws.memory_bytes is not None else tpl.memory_bytes,
        pids_limit=ws.pids_limit if ws.pids_limit is not None else tpl.pids_limit,
        workspace_host=settings.workspace_host(str(ws.id)),
    )


def process(op: m.WorkspaceOperation, driver: RuntimeDriver) -> None:
    with factory() as db:
        # Re-fetch in this session: the claimed object may be detached.
        op = db.get(m.WorkspaceOperation, op.id)
        ws = db.get(m.Workspace, op.workspace_id)
        if not ws:
            op.state = m.OP_FAILED; op.error_code = "WORKSPACE_MISSING"; db.commit(); return
        # Disable always wins over stale starts.
        if op.op == m.OP_START and not ws.enabled:
            op.state = m.OP_SUCCEEDED; db.commit(); return
        try:
            spec = _spec_for(db, ws)
            if op.op == m.OP_START:
                # Every start gets a fresh workspace token; revoke any old one.
                for old in db.query(m.RuntimeCredential).filter(
                    m.RuntimeCredential.workspace_id == ws.id,
                    m.RuntimeCredential.revoked_at.is_(None),
                ):
                    old.revoked_at = datetime.now(timezone.utc)
                cache = getattr(driver, "_credentials", None)
                if cache is not None:
                    cache.pop((str(ws.id), ws.generation), None)
                driver.ensure(spec)
                driver.start(spec)
                driver.attach_gateway(spec)
                cred = driver.credential(spec)
                token = cred
                exists = db.query(m.RuntimeCredential).filter(
                    m.RuntimeCredential.token_hash == token_hash(token),
                    m.RuntimeCredential.revoked_at.is_(None),
                ).first()
                if not exists:
                    db.add(m.RuntimeCredential(
                        id=uuid.uuid4(), token_hash=token_hash(token), workspace_id=ws.id,
                        generation=ws.generation,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    ))
                ws.observed_state = m.OBS_RUNNING
                ws.error_code = None
            elif op.op == m.OP_STOP or op.op == m.OP_DISABLE:
                for cred in db.query(m.RuntimeCredential).filter(
                    m.RuntimeCredential.workspace_id == ws.id, m.RuntimeCredential.revoked_at.is_(None)
                ):
                    cred.revoked_at = datetime.now(timezone.utc)
                driver.stop(spec)
                ws.observed_state = m.OBS_STOPPED
            elif op.op == m.OP_REBUILD:
                from dataclasses import replace
                new_gen = op.target_generation or (ws.generation + 1)
                new_spec = replace(spec, generation=new_gen)
                driver.rebuild(spec, new_spec)
                for old in db.query(m.RuntimeCredential).filter(
                    m.RuntimeCredential.workspace_id == ws.id,
                    m.RuntimeCredential.revoked_at.is_(None),
                ):
                    old.revoked_at = datetime.now(timezone.utc)
                ws.generation = new_gen
                cred = driver.credential(new_spec)
                exists = db.query(m.RuntimeCredential).filter(
                    m.RuntimeCredential.token_hash == token_hash(cred),
                    m.RuntimeCredential.revoked_at.is_(None),
                ).first()
                if not exists:
                    db.add(m.RuntimeCredential(
                        id=uuid.uuid4(), token_hash=token_hash(cred), workspace_id=ws.id,
                        generation=new_gen,
                        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                    ))
                ws.observed_state = m.OBS_RUNNING
            elif op.op == m.OP_ENABLE:
                ws.observed_state = ws.observed_state
            op.state = m.OP_SUCCEEDED
            op.finished_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            import traceback
            print("[worker] operation failed:", op.id, type(exc).__name__, str(exc), flush=True)
            traceback.print_exc()
            op.state = m.OP_FAILED
            op.error_code = type(exc).__name__
            op.finished_at = datetime.now(timezone.utc)
            ws.observed_state = m.OBS_ERROR
            ws.error_code = type(exc).__name__
            db.commit()


def reconcile(driver: RuntimeDriver) -> None:
    """Enqueue missing transitions and take over expired leases."""
    with factory() as db:
        now = datetime.now(timezone.utc)
        rows = db.query(m.Workspace).all()
        for ws in rows:
            # Re-attach relay/llm after a gateway service container is recreated.
            # attach_gateway is idempotent (skips networks already attached).
            if ws.enabled and ws.observed_state == m.OBS_RUNNING:
                try:
                    driver.attach_gateway(_spec_for(db, ws))
                except Exception:
                    pass
            pending = db.query(m.WorkspaceOperation).filter(
                m.WorkspaceOperation.workspace_id == ws.id,
                m.WorkspaceOperation.state.in_([m.OP_QUEUED, m.OP_RUNNING]),
            ).count()
            if pending:
                continue
            desired_op = None
            if ws.enabled and ws.desired_state == m.DESIRED_RUNNING and ws.observed_state != m.OBS_RUNNING:
                desired_op = m.OP_START
            elif (not ws.enabled or ws.desired_state == m.DESIRED_STOPPED) and ws.observed_state == m.OBS_RUNNING:
                desired_op = m.OP_STOP
            # Rotate a token that expires within 10 minutes by rebuilding the
            # space on its next generation; volumes are reused.
            if desired_op is None and ws.enabled and ws.observed_state == m.OBS_RUNNING:
                active = db.query(m.RuntimeCredential).filter(
                    m.RuntimeCredential.workspace_id == ws.id,
                    m.RuntimeCredential.revoked_at.is_(None),
                ).first()
                if active and active.expires_at - now <= timedelta(minutes=10):
                    desired_op = m.OP_REBUILD
            if desired_op:
                target_gen = ws.generation + 1 if desired_op == m.OP_REBUILD else ws.generation
                try:
                    db.add(m.WorkspaceOperation(
                        id=uuid.uuid4(), workspace_id=ws.id, actor_id=ws.owner_id,
                        op=desired_op,
                        idempotency_key=f"reconcile-{desired_op}-{ws.generation}-{int(now.timestamp())}",
                        request_hash=f"reconcile:{desired_op}:{ws.id}:{ws.generation}",
                        state=m.OP_QUEUED, target_generation=target_gen,
                    ))
                    db.commit()
                except IntegrityError:
                    # One active change per workspace: another reconcilers won.
                    db.rollback()
        db.commit()


def run_forever() -> None:
    driver = DockerRuntimeDriver(settings.installation_id)
    last = 0.0
    while True:
        if time.monotonic() - last > 15:
            reconcile(driver)
            last = time.monotonic()
        with factory() as db:
            op = _claim_one(db)
        if op:
            process(op, driver)
        else:
            time.sleep(1)


if __name__ == "__main__":
    run_forever()
