"""In-process registry of live workspace connections.

The first release runs a single API process, so an in-process registry is enough.
Every connection is revalidated against the control DB at most every 2 seconds;
disable / logout / tenant switch / membership revocation broadcast an immediate
close. DB failure closes connections that cannot be revalidated.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable

from sqlalchemy import select

from harness_common import models as m


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
    def __init__(self, factory_provider, *, interval: float = 2.0):
        self._conns: dict[str, LiveConnection] = {}
        self._lock = asyncio.Lock()
        self._factory_provider = factory_provider
        self._interval = interval
        self._task: asyncio.Task | None = None

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

    async def close_workspace(self, wid: uuid.UUID) -> int:
        return await self._close_matching(lambda c: c.workspace_id == wid)

    async def close_workspaces(self, ids: set[uuid.UUID]) -> int:
        return await self._close_matching(lambda c: c.workspace_id in ids)

    async def close_auth_session(self, sid: uuid.UUID) -> int:
        return await self._close_matching(lambda c: c.auth_session_id == sid)

    async def close_user(self, uid: uuid.UUID) -> int:
        return await self._close_matching(lambda c: c.user_id == uid)

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
                pass  # keep the loop alive

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
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
