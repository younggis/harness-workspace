"""Offline tests for the live-connection registry and revocation broadcast."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from conftest import seed_world
from harness_common import models as m
from services.api.app.connections import ConnectionRegistry, LiveConnection


def _seed_session(app, wid, uid):
    from harness_common.security import new_token, token_hash
    with app.state.session_factory() as db:
        auth = m.AuthSession(
            id=uuid.uuid4(), token_hash=token_hash(new_token()), user_id=uid,
            active_tenant_id=db.execute(
                select_tenant_id(db, wid)
            ).scalar_one_or_none(),
            csrf_hash=token_hash(new_token()),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(auth); db.flush()
        ws_sess = m.WorkspaceSession(
            id=uuid.uuid4(), token_hash=token_hash(new_token()), auth_session_id=auth.id,
            workspace_id=wid, epoch=0,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(ws_sess); db.commit()
        return auth.id, ws_sess.id


def select_tenant_id(db, wid):
    from sqlalchemy import select
    return select(m.Workspace.tenant_id).where(m.Workspace.id == wid)


@pytest.mark.asyncio
async def test_close_workspace_broadcasts_and_removes(app):
    w = seed_world(app)
    aid, sid = _seed_session(app, w["wsA1"], w["A1"])
    calls = []
    reg = ConnectionRegistry(lambda: app.state.session_factory, interval=999)

    async def close():
        calls.append("closed")

    await reg.register(LiveConnection(
        id="c1", kind="ws", workspace_id=w["wsA1"], ws_session_id=sid,
        auth_session_id=aid, user_id=w["A1"], epoch=0, generation=0, close=close,
    ))
    assert reg.count == 1
    n = await reg.close_workspace(w["wsA1"])
    assert n == 1 and calls == ["closed"] and reg.count == 0


@pytest.mark.asyncio
async def test_revalidate_closes_on_auth_revocation(app):
    w = seed_world(app)
    aid, sid = _seed_session(app, w["wsA1"], w["A1"])
    with app.state.session_factory() as db:
        db.get(m.AuthSession, aid).revoked_at = datetime.now(timezone.utc)
        db.commit()
    calls = []
    reg = ConnectionRegistry(lambda: app.state.session_factory)

    async def close():
        calls.append("closed")

    await reg.register(LiveConnection(
        id="c2", kind="sse", workspace_id=w["wsA1"], ws_session_id=sid,
        auth_session_id=aid, user_id=w["A1"], epoch=0, generation=0, close=close,
    ))
    await reg.revalidate_once()
    assert calls == ["closed"] and reg.count == 0


@pytest.mark.asyncio
async def test_revalidate_closes_on_workspace_disable_and_epoch(app):
    w = seed_world(app)
    aid, sid = _seed_session(app, w["wsA1"], w["A1"])
    with app.state.session_factory() as db:
        db.get(m.Workspace, w["wsA1"]).enabled = False
        db.commit()
    calls = []
    reg = ConnectionRegistry(lambda: app.state.session_factory)

    async def close():
        calls.append("closed")

    await reg.register(LiveConnection(
        id="c3", kind="ws", workspace_id=w["wsA1"], ws_session_id=sid,
        auth_session_id=aid, user_id=w["A1"], epoch=0, generation=0, close=close,
    ))
    await reg.revalidate_once()
    assert calls == ["closed"] and reg.count == 0


@pytest.mark.asyncio
async def test_revalidate_closes_when_db_unavailable(app):
    reg = ConnectionRegistry(lambda: (_ for _ in ()).throw(RuntimeError("DB down")))
    calls = []

    async def close():
        calls.append("closed")

    await reg.register(LiveConnection(
        id="c4", kind="ws", workspace_id=uuid.uuid4(), ws_session_id=uuid.uuid4(),
        auth_session_id=uuid.uuid4(), user_id=uuid.uuid4(), epoch=0, generation=0, close=close,
    ))
    await reg.revalidate_once()
    assert calls == ["closed"] and reg.count == 0


@pytest.mark.asyncio
async def test_close_user_and_auth_session(app):
    w = seed_world(app)
    aid, sid = _seed_session(app, w["wsA1"], w["A1"])
    reg = ConnectionRegistry(lambda: app.state.session_factory)
    calls = []

    async def close():
        calls.append("closed")

    await reg.register(LiveConnection(
        id="c5", kind="ws", workspace_id=w["wsA1"], ws_session_id=sid,
        auth_session_id=aid, user_id=w["A1"], epoch=0, generation=0, close=close,
    ))
    assert await reg.close_user(uuid.uuid4()) == 0
    assert await reg.close_auth_session(aid) == 1
    assert calls == ["closed"]
