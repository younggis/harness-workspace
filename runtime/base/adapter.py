"""In-runtime HTTP adapter in front of the native dsh web server.

dsh listens on loopback 3080. The adapter owns the one-time root token->cookie
exchange using a single, fixed UPSTREAM_AUTHORITY, then injects that cookie on
every subsequent HTTP/WS request. No platform cookies/authorization reach dsh.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

app = FastAPI(title="Harness Workspace Adapter")
PUBLIC_HOST = os.environ.get("DSH_TRUSTED_HOST", "localhost")
PUBLIC_AUTHORITY = PUBLIC_HOST.split(":", 1)[0]
# One authority for ALL upstream traffic. The hostname resolves to 127.0.0.1
# via loopback DNS, so websockets (which derives Host from the URI) and HTTP
# present the exact same Host that was used to issue the session cookie.
UPSTREAM = f"http://{PUBLIC_AUTHORITY}:3080"
UPSTREAM_AUTHORITY = f"{PUBLIC_AUTHORITY}:3080"
_cookie: str = ""


def _safe_headers(request: Request) -> dict:
    out = {}
    for k, v in request.headers.items():
        kl = k.lower()
        if kl in ("cookie", "authorization", "x-harness-signature", "host", "origin"):
            continue
        if kl in ("content-type", "accept", "if-match", "if-none-match", "x-request-id",
                  "sec-websocket-protocol"):
            out[k] = v
    out["Host"] = UPSTREAM_AUTHORITY
    out["Origin"] = f"http://{UPSTREAM_AUTHORITY}"
    if _cookie:
        out["Cookie"] = _cookie
    return out


def exchange_once() -> bool:
    """Perform the root token -> signed cookie exchange against loopback dsh."""
    global _cookie
    launch_url = os.environ.get("DSH_LAUNCH_URL", "")
    if not launch_url:
        return False
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(launch_url)
        upstream = f"{UPSTREAM}/"
        if parts.query:
            upstream += "?" + parts.query
        with httpx.Client(follow_redirects=False, timeout=10.0) as client:
            r = client.get(upstream, headers={"Host": UPSTREAM_AUTHORITY})
            print(f"[adapter] exchange status={r.status_code} cookie={'set-cookie' in r.headers}", flush=True)
            if r.status_code in (302, 303) and "set-cookie" in r.headers:
                _cookie = r.headers["set-cookie"].split(";", 1)[0]
                return True
    except Exception as exc:
        print(f"[adapter] exchange error: {type(exc).__name__}: {exc}", flush=True)
    return False


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy(path: str, request: Request):
    if not _cookie:
        exchange_once()
    body = await request.body()
    url = f"{UPSTREAM}/{path}"
    if request.url.query:
        url += "?" + request.url.query
    if path.endswith("/plugins/events"):
        client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(None, connect=10.0))
        req = client.build_request(request.method, url, content=body, headers=_safe_headers(request))
        resp = await client.send(req, stream=True)
        async def sse():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose(); await client.aclose()
        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})
    async with httpx.AsyncClient(follow_redirects=False, timeout=120.0) as client:
        resp = await client.request(request.method, url, content=body,
                                    headers=_safe_headers(request))
    out = Response(content=resp.content, status_code=resp.status_code,
                   media_type=resp.headers.get("content-type"))
    for h in ("etag", "cache-control", "content-disposition"):
        if h in resp.headers:
            out.headers[h] = resp.headers[h]
    # Never write upstream Set-Cookie back to the platform browser.
    return out


@app.websocket("/{path:path}")
async def ws_proxy(path: str, websocket: WebSocket):
    await websocket.accept()
    try:
        if not _cookie:
            exchange_once()
        import websockets
        target = f"ws://{UPSTREAM_AUTHORITY}/{path}"
        if websocket.url.query:
            target += "?" + websocket.url.query
        subprotos = [s.strip() for s in (websocket.headers.get("sec-websocket-protocol") or "").split(",") if s.strip()]
        async with websockets.connect(target, additional_headers=_safe_headers(websocket),
                                      subprotocols=subprotos or None) as up:
            async def c2u():
                while True:
                    msg = await websocket.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    if msg.get("bytes") is not None:
                        await up.send(msg["bytes"])
                    else:
                        await up.send(msg.get("text", ""))
            async def u2c():
                async for d in up:
                    if isinstance(d, bytes):
                        await websocket.send_bytes(d)
                    else:
                        await websocket.send_text(d)
            import asyncio
            await asyncio.gather(c2u(), u2c())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import traceback
        print(f"[adapter-ws] {type(exc).__name__}: {exc}", flush=True)
        resp = getattr(exc, "response", None)
        if resp:
            print(f"[adapter-ws] resp={resp.status_code} body={getattr(resp,'body',b'')!r}", flush=True)
        traceback.print_exc()
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
