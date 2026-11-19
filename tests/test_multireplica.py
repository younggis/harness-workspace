"""Offline tests for cross-process revocation broadcast via a fake Redis pub/sub."""
import asyncio
import json
import uuid

import pytest

from conftest import seed_world
from harness_common import models as m
from services.api.app.connections import CHANNEL, ConnectionRegistry, LiveConnection


class FakePubSub:
    def __init__(self, bus):
        self.bus = bus
        self.subscribed = None

    def subscribe(self, channel):
        self.subscribed = channel
        self.bus["subscribed"].add(channel)

    def get_message(self, timeout=1.0):
        return None

    def close(self):
        pass


class FakeRedis:
    def __init__(self):
        self.published = []
        self.bus = {"subscribed": set()}

    def publish(self, channel, payload):
        self.published.append((channel, payload))

    def pubsub(self, **kwargs):
        return FakePubSub(self.bus)


@pytest.mark.asyncio
async def test_local_close_also_publishes(app):
    w = seed_world(app)
    bus = FakeRedis()
    reg = ConnectionRegistry(lambda: app.state.session_factory, redis_client=bus)
    calls = []

    async def close():
        calls.append("closed")

    await reg.register(LiveConnection(
        id="c1", kind="ws", workspace_id=w["wsA1"], ws_session_id=uuid.uuid4(),
        auth_session_id=uuid.uuid4(), user_id=w["A1"], epoch=0, generation=0, close=close,
    ))
    n = await reg.close_user(w["A1"])
    assert n == 1 and calls == ["closed"]
    assert len(bus.published) == 1
    channel, payload = bus.published[0]
    assert channel == CHANNEL
    msg = json.loads(payload)
    assert msg["kind"] == "user" and msg["ids"] == [str(w["A1"])]


@pytest.mark.asyncio
async def test_remote_message_closes_second_replica(app):
    w = seed_world(app)
    replica_a = FakeRedis()
    replica_b = FakeRedis()
    reg_a = ConnectionRegistry(lambda: app.state.session_factory, redis_client=replica_a)
    reg_b = ConnectionRegistry(lambda: app.state.session_factory, redis_client=replica_b)
    assert reg_a._instance_id != reg_b._instance_id

    closed_b = []

    async def close_b():
        closed_b.append("closed")

    await reg_b.register(LiveConnection(
        id="c2", kind="ws", workspace_id=w["wsA1"], ws_session_id=uuid.uuid4(),
        auth_session_id=uuid.uuid4(), user_id=w["A1"], epoch=0, generation=0, close=close_b,
    ))
    # A broadcasts a workspace revocation; B receives it.
    await reg_a.close_workspace(w["wsA1"])
    channel, payload = replica_a.published[0]
    await reg_b._handle_message(payload)
    assert closed_b == ["closed"] and reg_b.count == 0
