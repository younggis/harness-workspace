"""Workspace entry tickets, host-bound session exchange, and the signed gateway.

The browser only ever reaches `edge`. For workspace hosts, `edge` forwards to this
router, which authenticates and then proxies through `relay` to the space runtime.
Relay verifies a short-lived HMAC bound to method/path/workspace/generation.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Form, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select

from harness_common import models as m
from harness_common.config import get_settings
from harness_common.errors import APIError
from harness_common.security import (
    new_token, sign_relay_request, sha256_text, token_hash,
)

from .. import schemas as s
from ..connections import LiveConnection
from ..deps import CSRF_COOKIE, CsrfDep, DbSession, IdentityDep, SettingsDep, WsDbSession

router = APIRouter()

WS_COOKIE = "harness_ws"
RELAY_BASE = os.environ.get("RELAY_BASE_URL", "http://relay:8081")
TICKET_TTL = 60
WS_TTL = 8 * 3600


def _workspace_host(host: str, workspace_id: uuid.UUID, settings) -> str:
    return f"w-{workspace_id}{settings.workspace_host_suffix}"


def _request_host(request: Request) -> str:
    return request.headers.get("host", "").split(":", 1)[0]


def _require_workspace_session(request: Request, db, settings) -> tuple[m.Workspace, m.WorkspaceSession, m.AuthSession]:
    token = request.cookies.get(WS_COOKIE)
    if not token:
        raise APIError("UNAUTHENTICATED", "Workspace session required")
    ws_sess = db.execute(
        select(m.WorkspaceSession).where(m.WorkspaceSession.token_hash == token_hash(token))
    ).scalar_one_or_none()
    if not ws_sess or ws_sess.revoked_at or m.is_expired(ws_sess.expires_at):
        raise APIError("UNAUTHENTICATED", "Workspace session expired")
    ws = db.get(m.Workspace, ws_sess.workspace_id)
    if not ws or not ws.enabled:
        raise APIError("FORBIDDEN", "Workspace disabled")
    if ws.auth_epoch != ws_sess.epoch:
        raise APIError("FORBIDDEN", "Workspace epoch changed")
    auth = db.get(m.AuthSession, ws_sess.auth_session_id)
    if not auth or auth.revoked_at or m.is_expired(auth.expires_at):
        raise APIError("UNAUTHENTICATED", "Portal session expired")
    expected_host = _workspace_host(_request_host(request), ws.id, settings)
    if _request_host(request) != expected_host.split(":")[0]:
        raise APIError("FORBIDDEN", "Host binding mismatch")
    return ws, ws_sess, auth


# ---- ticket creation (portal host) -----------------------------------------
@router.post("/api/workspaces/{wid}/entry-tickets", response_model=s.EntryTicketOut, status_code=201)
def create_ticket(wid: uuid.UUID, body: s.EntryTicketIn, request: Request, db: DbSession,
                  identity: IdentityDep, settings: SettingsDep, _csrf: CsrfDep):
    if identity.is_api_token:
        raise APIError("FORBIDDEN", "A browser session is required to enter a workspace")
    ws = db.get(m.Workspace, wid)
    if not ws or not ws.enabled or ws.tenant_id != identity.tenant_id:
        raise APIError("NOT_FOUND", "Workspace not found")
    if identity.role != m.MEMBER_ADMIN and ws.owner_id != identity.user.id and not identity.is_platform_admin:
        raise APIError("NOT_FOUND", "Workspace not found")
    if ws.observed_state != m.OBS_RUNNING:
        raise APIError("WORKSPACE_NOT_READY", "Workspace is not running", retryable=True)

    ticket = new_token()
    db.add(m.EntryTicket(
        id=uuid.uuid4(), ticket_hash=token_hash(ticket),
        auth_session_id=identity.session.id, workspace_id=wid,
        epoch=ws.auth_epoch, target=body.target,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=TICKET_TTL),
    ))
    db.add(m.AuditEvent(actor_id=identity.user.id, tenant_id=ws.tenant_id, workspace_id=wid,
                        action="entry.ticket.create", target=body.target, result="success",
                        request_id=request.state.request_id))
    db.commit()
    return s.EntryTicketOut(ticket=ticket, workspace_host=_workspace_host(_request_host(request), wid, settings),
                            target=body.target, expires_in=TICKET_TTL)


# ---- ticket exchange on workspace host -------------------------------------
@router.post("/_platform/enter")
def enter(request: Request, response: Response, db: DbSession, settings: SettingsDep,
          ticket: str = Form(...)):
    # Only the portal origin may submit this one cross-host form.
    if request.headers.get("origin") != settings.portal_origin:
        raise APIError("FORBIDDEN", "Origin check failed")
    host = _request_host(request)
    rec = db.execute(
        select(m.EntryTicket).where(m.EntryTicket.ticket_hash == token_hash(ticket))
    ).scalar_one_or_none()
    if not rec or rec.used_at or m.is_expired(rec.expires_at):
        raise APIError("FORBIDDEN", "Invalid or expired ticket")
    ws = db.get(m.Workspace, rec.workspace_id)
    if not ws or not ws.enabled or ws.auth_epoch != rec.epoch:
        raise APIError("FORBIDDEN", "Workspace epoch changed")
    if _workspace_host(_request_host(request), ws.id, settings).split(":")[0] != host:
        raise APIError("FORBIDDEN", "Host binding mismatch")
    auth = db.get(m.AuthSession, rec.auth_session_id)
    if not auth or auth.revoked_at:
        raise APIError("UNAUTHENTICATED", "Session revoked")

    # Atomic single-use consumption.
    rec.used_at = datetime.now(timezone.utc)
    ws_token = new_token()
    db.add(m.WorkspaceSession(
        id=uuid.uuid4(), token_hash=token_hash(ws_token), auth_session_id=auth.id,
        workspace_id=ws.id, epoch=ws.auth_epoch,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=WS_TTL),
    ))
    db.add(m.AuditEvent(actor_id=auth.user_id, tenant_id=ws.tenant_id, workspace_id=ws.id,
                        action="entry.exchange", target=rec.target, result="success",
                        request_id=request.state.request_id))
    db.commit()

    secure = str(settings.portal_origin).startswith("https://")
    response.set_cookie(WS_COOKIE, ws_token, max_age=WS_TTL, httponly=True,
                        samesite="lax", secure=secure, path="/", domain=None)
    target_path = {
        "agent": "/", "files": "/_platform/ui/files", "terminal": "/_platform/ui/terminal",
    }.get(rec.target, "/")
    return RedirectResponse(url=target_path, status_code=303, headers=dict(response.headers))


@router.get("/_platform/me")
def platform_me(request: Request, db: DbSession, settings: SettingsDep):
    ws, _, _ = _require_workspace_session(request, db, settings)
    return {"workspace_id": str(ws.id), "tenant_id": str(ws.tenant_id),
            "generation": ws.generation, "epoch": ws.auth_epoch,
            "csrf_token": new_token(24)}


# ---- generic signed proxy to the workspace runtime via relay ---------------
async def _proxy(request: Request, db, settings, *, target_path: str | None = None) -> JSONResponse:
    ws, ws_sess, auth = _require_workspace_session(request, db, settings)
    path = target_path or request.url.path
    body = await request.body()
    headers = {
        "X-Harness-Signature": sign_relay_request(
            settings.relay_signing_key, method=request.method, path=path,
            workspace_id=str(ws.id), generation=ws.generation,
        ),
        "X-Harness-Workspace": str(ws.id),
        "X-Harness-Generation": str(ws.generation),
    }
    # Strip all platform cookies/authorization; forward only safe hop headers.
    for name, value in request.headers.items():
        if name.lower() in ("content-type", "if-match", "if-none-match", "accept", "x-request-id"):
            headers[name] = value
    url = f"{RELAY_BASE}{path}"
    if request.url.query:
        url += "?" + request.url.query
    if path.endswith("/plugins/events"):
        client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))
        req = client.build_request(request.method, url, content=body, headers=headers)
        upstream = await client.send(req, stream=True)
        close_event = asyncio.Event()
        cid = str(uuid.uuid4())
        await request.app.state.connections.register(LiveConnection(
            id=cid, kind="sse", workspace_id=ws.id, ws_session_id=ws_sess.id,
            auth_session_id=auth.id, user_id=auth.user_id, epoch=ws.auth_epoch,
            generation=ws.generation, close=lambda: close_event.set(),
        ))
        async def sse():
            chunks = upstream.aiter_bytes()
            try:
                while not close_event.is_set():
                    stream_task = asyncio.create_task(chunks.__anext__())
                    close_task = asyncio.create_task(close_event.wait())
                    done, pending = await asyncio.wait(
                        [stream_task, close_task], return_when=asyncio.FIRST_COMPLETED,
                    )
                    for t in pending:
                        t.cancel()
                    if close_task in done:
                        break
                    try:
                        yield stream_task.result()
                    except StopAsyncIteration:
                        break
            finally:
                await request.app.state.connections.unregister(cid)
                await upstream.aclose(); await client.aclose()
        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    async with httpx.AsyncClient(timeout=60.0) as client:
        upstream = await client.request(request.method, url, content=body, headers=headers)
    content_type = upstream.headers.get("content-type", "")
    if "application/json" in content_type:
        resp = JSONResponse(content=_safe_json(upstream.content), status_code=upstream.status_code)
    else:
        # Native Web serves HTML/JS/CSS; forward bytes verbatim, never JSON-wrap.
        resp = Response(content=upstream.content, status_code=upstream.status_code,
                        media_type=content_type or None)
    for h in ("etag", "content-disposition", "cache-control"):
        if h in upstream.headers:
            resp.headers[h] = upstream.headers[h]
    # Never forward upstream Set-Cookie back to the platform browser.
    return resp


def _safe_json(content: bytes):
    import json
    try:
        return json.loads(content)
    except Exception:
        return {"raw": content.decode("utf-8", "replace")[:2000]}


@router.get("/_platform/files")
async def files_list(request: Request, db: DbSession, settings: SettingsDep):
    return await _proxy(request, db, settings)


@router.api_route("/_platform/file", methods=["GET", "PUT", "DELETE"])
async def file_item(request: Request, db: DbSession, settings: SettingsDep):
    return await _proxy(request, db, settings)


@router.post("/_platform/directories")
async def make_dir(request: Request, db: DbSession, settings: SettingsDep):
    return await _proxy(request, db, settings)


@router.post("/_platform/moves")
async def move_item(request: Request, db: DbSession, settings: SettingsDep):
    return await _proxy(request, db, settings)


# ---- WebSocket gateway (terminal + native dsh paths) -----------------------
async def _proxy_ws(websocket: WebSocket, path: str) -> None:
    settings = get_settings()
    db = websocket.app.state.session_factory()
    try:
        token = websocket.cookies.get(WS_COOKIE)
        origin = websocket.headers.get("origin")
        host_header = websocket.headers.get("host", "")
        host = host_header.split(":", 1)[0]
        if not token or not origin:
            await websocket.close(code=4401); return
        sess = db.execute(
            select(m.WorkspaceSession).where(m.WorkspaceSession.token_hash == token_hash(token))
        ).scalar_one_or_none()
        if not sess or sess.revoked_at or m.is_expired(sess.expires_at):
            await websocket.close(code=4401); return
        ws = db.get(m.Workspace, sess.workspace_id)
        if not ws or not ws.enabled or ws.auth_epoch != sess.epoch:
            await websocket.close(code=4403); return
        expected_host = _workspace_host(host, ws.id, settings).split(":")[0]
        expected_origin = f"http://{expected_host}:8080" if host_header.endswith(":8080") else f"http://{expected_host}"
        if host != expected_host or origin != expected_origin:
            await websocket.close(code=4403); return
        auth = db.get(m.AuthSession, sess.auth_session_id)
        if not auth:
            await websocket.close(code=4401); return
        await websocket.accept()
        cid = str(uuid.uuid4())
        async def close_ws():
            await websocket.close(code=4403)
        await websocket.app.state.connections.register(LiveConnection(
            id=cid, kind="ws", workspace_id=ws.id, ws_session_id=sess.id,
            auth_session_id=auth.id, user_id=auth.user_id, epoch=ws.auth_epoch,
            generation=ws.generation, close=close_ws,
        ))
        sig = sign_relay_request(settings.relay_signing_key, method="GET", path=path,
                                 workspace_id=str(ws.id), generation=ws.generation)
        relay_ws = f"ws://relay:8081{path}?sig={sig}&w={ws.id}&g={ws.generation}"
        import websockets
        subprotos = [s.strip() for s in (websocket.headers.get("sec-websocket-protocol") or "").split(",") if s.strip()]
        async with websockets.connect(relay_ws, subprotocols=subprotos or None) as upstream:
            async def c2u():
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("bytes") is not None:
                        await upstream.send(msg["bytes"])
                    else:
                        await upstream.send(msg.get("text", ""))
            async def u2c():
                async for data in upstream:
                    if isinstance(data, bytes):
                        await websocket.send_bytes(data)
                    else:
                        await websocket.send_text(data)
            import asyncio
            await asyncio.gather(c2u(), u2c())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import traceback
        print(f"[ws-proxy] {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await websocket.app.state.connections.unregister(cid) if "cid" in locals() else None
        db.close()


@router.websocket("/_platform/terminal")
async def terminal_ws(websocket: WebSocket):
    await _proxy_ws(websocket, "/_platform/terminal")


@router.websocket("/{path:path}")
async def native_ws(path: str, websocket: WebSocket):
    await _proxy_ws(websocket, "/" + path)


# ---- catch-all: native dsh HTTP/WS paths on a workspace host ---------------
@router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def native_proxy(full_path: str, request: Request, db: DbSession, settings: SettingsDep):
    if not _request_host(request).startswith("w-"):
        raise APIError("NOT_FOUND", "Not found")
    return await _proxy(request, db, settings, target_path="/" + full_path)
