"""Relay: verifies API signatures on every reachable interface, forwards only to
the service-generated target (`rt-<workspace>-g<generation>`). No browser-supplied
addresses, no CONNECT, no generic proxying, no platform/model secrets.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse

from harness_common.config import get_settings
from harness_common.errors import APIError, api_error_handler
from harness_common.security import verify_relay_signature

settings = get_settings()
app = FastAPI(title="Harness Relay")
app.add_exception_handler(APIError, api_error_handler)
RUNTIME_PORT = 8080


def _verify(request: Request, path: str) -> tuple[str, int]:
    sig = request.headers.get("x-harness-signature", "")
    wid = request.headers.get("x-harness-workspace", "")
    gen = request.headers.get("x-harness-generation", "")
    if not sig or not wid or not gen:
        raise APIError("FORBIDDEN", "Relay signature required")
    try:
        generation = int(gen)
    except ValueError:
        raise APIError("FORBIDDEN", "Invalid generation")
    if not verify_relay_signature(settings.relay_signing_key, sig,
                                  method=request.method, path=path,
                                  workspace_id=wid, generation=generation):
        raise APIError("FORBIDDEN", "Relay signature verification failed")
    return wid, generation


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def forward(path: str, request: Request):
    wid, gen = _verify(request, "/" + path)
    target = f"http://rt-{wid}-g{gen}:{RUNTIME_PORT}/{path}"
    if request.url.query:
        target += "?" + request.url.query
    body = await request.body()
    headers = {}
    for k, v in request.headers.items():
        if k.lower() in ("content-type", "if-match", "if-none-match", "accept", "x-request-id", "origin"):
            headers[k] = v
    if path.endswith("/plugins/events"):
        client = httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0))
        req = client.build_request(request.method, target, content=body, headers=headers)
        resp = await client.send(req, stream=True)
        async def sse():
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose(); await client.aclose()
        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.request(request.method, target, content=body, headers=headers)
    out = Response(content=resp.content, status_code=resp.status_code, media_type=resp.headers.get("content-type"))
    for h in ("etag", "content-disposition", "cache-control"):
        if h in resp.headers:
            out.headers[h] = resp.headers[h]
    return out


@app.websocket("/{path:path}")
async def forward_ws(path: str, websocket: WebSocket):
    await websocket.accept()
    try:
        sig = websocket.query_params.get("sig", "")
        wid = websocket.query_params.get("w", "")
        gen = websocket.query_params.get("g", "")
        ws_path = "/" + path
        if not verify_relay_signature(settings.relay_signing_key, sig, method="GET",
                                      path=ws_path, workspace_id=wid, generation=int(gen)):
            await websocket.close(code=4403); return
        target = f"ws://rt-{wid}-g{gen}:{RUNTIME_PORT}{ws_path}"
        import websockets
        subprotos = [s.strip() for s in (websocket.headers.get("sec-websocket-protocol") or "").split(",") if s.strip()]
        async with websockets.connect(target, subprotocols=subprotos or None) as upstream:
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
    except Exception as exc:
        import traceback
        print(f"[relay-ws] {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        try:
            await websocket.close(code=1011)
        except Exception:
            pass


@app.get("/health/live")
def live():
    return {"status": "ok"}
