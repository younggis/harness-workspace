"""Registry of live workspace connections with cross-process revocation.

Single replica: in-process close + a <=2s DB revalidation loop.
Multiple replicas: revocations are published to Redis so every API replica closes
matching WS/SSE connections immediately. DB revalidation remains the safety net
if Redis is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select

from harness_common import models as m

CHANNEL = "harness:revocations"


@dataclass
class LiveConnection:
    id: str
    kind: str  # "ws" | "sse"
    workspace_id: uuid.UUID
    ws_session_id: uuid.UUID
    auth_session_id: uuid.UUID
    user_id: uuid.UUID
    epoch: int
    generation: int
    close: Callable[[], Awaitable[None]]


class ConnectionRegistry:
    def __init__(self, factory_provider, *, interval: float = 2.0,
                 redis_url: str = "", redis_client=None):
        self._conns: dict[str, LiveConnection] = {}
        self._lock = asyncio.Lock()
        self._factory_provider = factory_provider
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._listener: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._instance_id = uuid.uuid4().hex
        self._redis = redis_client
        self._pubsub = None
        self._stop_event = threading.Event()
        if self._redis is None and redis_url:
            try:
                import redis
                self._redis = redis.Redis.from_url(redis_url, socket_timeout=2, socket_connect_timeout=2)
            except Exception:
                self._redis = None

    async def register(self, conn: LiveConnection) -> str:
        async with self._lock:
            self._conns[conn.id] = conn
        return conn.id

    async def unregister(self, cid: str) -> None:
        async with self._lock:
            self._conns.pop(cid, None)

    async def _close_matching(self, predicate) -> int:
        async with self._lock:
            targets = [c for c in self._conns.values() if predicate(c)]
        for c in targets:
            try:
                await c.close()
            except Exception:
                pass
            await self.unregister(c.id)
        return len(targets)

    async def _publish(self, kind: str, ids: list[str]) -> None:
        """Broadcast a revocation to other API replicas (best effort)."""
        if not self._redis:
            return
        payload = json.dumps({"sender": self._instance_id, "kind": kind, "ids": ids})
        try:
            await asyncio.to_thread(self._redis.publish, CHANNEL, payload)
        except Exception:
            pass  # Redis down: the 2s DB revalidation still closes the connection

    async def close_workspace(self, wid: uuid.UUID) -> int:
        n = await self._close_matching(lambda c: c.workspace_id == wid)
        await self._publish("workspace", [str(wid)])
        return n

    async def close_workspaces(self, ids: set[uuid.UUID]) -> int:
        n = await self._close_matching(lambda c: c.workspace_id in ids)
        await self._publish("workspace", [str(x) for x in ids])
        return n

    async def close_auth_session(self, sid: uuid.UUID) -> int:
        n = await self._close_matching(lambda c: c.auth_session_id == sid)
        await self._publish("session", [str(sid)])
        return n

    async def close_user(self, uid: uuid.UUID) -> int:
        n = await self._close_matching(lambda c: c.user_id == uid)
        await self._publish("user", [str(uid)])
        return n

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if msg.get("sender") == self._instance_id:
            return  # own broadcast already handled locally
        kind, ids = msg.get("kind"), set(msg.get("ids") or [])
        if kind == "workspace":
            parsed = {uuid.UUID(x) for x in ids if _is_uuid(x)}
            await self._close_matching(lambda c: c.workspace_id in parsed)
        elif kind == "session":
            parsed = {uuid.UUID(x) for x in ids if _is_uuid(x)}
            await self._close_matching(lambda c: c.auth_session_id in parsed)
        elif kind == "user":
            parsed = {uuid.UUID(x) for x in ids if _is_uuid(x)}
            await self._close_matching(lambda c: c.user_id in parsed)

    def _listen_loop(self) -> None:
        """Blocking pub/sub reader (runs in a thread)."""
        loop = self._loop
        try:
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            self._pubsub.subscribe(CHANNEL)
            while not self._stop_event.is_set():
                message = self._pubsub.get_message(timeout=1.0)
                if not message or message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", "replace")
                asyncio.run_coroutine_threadsafe(self._handle_message(data), loop)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _listen(self) -> None:
        await asyncio.to_thread(self._listen_loop)

    def _valid_sync(self, conn: LiveConnection) -> bool:
        with self._factory_provider()() as db:
            sess = db.get(m.WorkspaceSession, conn.ws_session_id)
            auth = db.get(m.AuthSession, conn.auth_session_id)
            ws = db.get(m.Workspace, conn.workspace_id)
            user = db.get(m.User, conn.user_id)
            if not (sess and auth and ws and user):
                return False
            if sess.revoked_at or m.is_expired(sess.expires_at) or sess.epoch != conn.epoch:
                return False
            if auth.revoked_at or m.is_expired(auth.expires_at):
                return False
            if user.status != m.USER_ACTIVE:
                return False
            if not ws.enabled or ws.auth_epoch != conn.epoch or ws.generation != conn.generation:
                return False
            return True

    async def revalidate_once(self) -> None:
        async with self._lock:
            conns = list(self._conns.values())
        for c in conns:
            try:
                valid = await asyncio.to_thread(self._valid_sync, c)
            except Exception:
                valid = False  # DB unavailable: cannot revalidate -> close
            if not valid:
                try:
                    await c.close()
                except Exception:
                    pass
                await self.unregister(c.id)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.revalidate_once()
            except Exception:
                pass

    def start(self) -> None:
        if self._task is None:
            self._loop = asyncio.get_running_loop()
            self._task = asyncio.create_task(self._run())
            if self._redis:
                self._listener = asyncio.create_task(self._listen())

    async def stop(self) -> None:
        for task in (self._task, self._listener):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._listener = None
        self._stop_event.set()
        if self._pubsub:
            try:
                self._pubsub.close()
            except Exception:
                pass
        async with self._lock:
            conns = list(self._conns.values())
            self._conns.clear()
        for c in conns:
            try:
                await c.close()
            except Exception:
                pass

    @property
    def count(self) -> int:
        return len(self._conns)


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False
