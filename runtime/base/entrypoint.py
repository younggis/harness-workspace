"""Runtime supervisor: starts native dsh, serves platform file/PTY APIs and the
native Web adapter, and keeps the model token in a restricted per-space file.

Supervisor is the parent of dsh, so container stop tears down the whole session.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import threading

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

import adapter
import fileservice
from ptyservice import PTYSession

app = FastAPI(title="Harness Runtime Adapter")
fileservice.open_root("/workspace")
_terminals: dict[str, PTYSession] = {}
_dsh: subprocess.Popen | None = None


@app.on_event("startup")
async def start_dsh():
    global _dsh
    host = os.environ.get("DSH_TRUSTED_HOST", "localhost")
    cmd = [
        "dsh", "--patch", "/opt/harness/profile/cordis.patch.yml",
        "--profile", "web", "--no-open",
        "--public-url", f"http://{host}/",
        "--trusted-host", host,
        "--trusted-host", host.split(":", 1)[0],
        "--trusted-host", f"{host.split(':', 1)[0]}:3080",
    ]
    # dsh prints a launch URL containing a one-time token. Capture in memory only;
    # never log it. Set DSH_LAUNCH_URL for the adapter's root exchange.
    _dsh = subprocess.Popen(cmd, cwd="/workspace", stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    # Read the one printed launch URL synchronously so the token->cookie exchange
    # happens only once dsh is actually listening. The URL is never logged.
    for line in _dsh.stdout or []:
        m = re.search(r"https?://\S+\?token=\S+", line)
        if m:
            os.environ["DSH_LAUNCH_URL"] = m.group(0).rstrip(").,")
            break
    adapter.exchange_once()


@app.on_event("shutdown")
async def stop_dsh():
    if _dsh and _dsh.poll() is None:
        _dsh.terminate()
        try:
            _dsh.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _dsh.kill()


# ---- platform file APIs -----------------------------------------------------
@app.get("/_platform/files")
def files_list(path: str = "."):
    try:
        return {"items": fileservice.list_dir(path)}
    except ValueError as e:
        return Response(status_code=400, content=str(e))


@app.get("/_platform/file")
def file_get(path: str):
    try:
        data, etag = fileservice.read_file(path)
        return Response(content=data, media_type="application/octet-stream", headers={"ETag": etag})
    except ValueError as e:
        return Response(status_code=400 if "PATH" in str(e) else 404, content=str(e))


@app.put("/_platform/file")
async def file_put(request: Request, path: str):
    data = await request.body()
    create = request.headers.get("if-none-match") == "*"
    try:
        etag = fileservice.write_file(path, data, etag=request.headers.get("if-match"), create=create)
        return {"etag": etag}
    except ValueError as e:
        code = {"VERSION_CONFLICT": 412, "PAYLOAD_TOO_LARGE": 413, "ALREADY_EXISTS": 409}.get(str(e), 400)
        return Response(status_code=code, content=str(e))


@app.delete("/_platform/file")
def file_delete(path: str):
    try:
        fileservice.delete_file(path)
        return Response(status_code=204)
    except ValueError as e:
        return Response(status_code=400, content=str(e))


@app.post("/_platform/directories")
async def dir_create(request: Request):
    body = await request.json()
    try:
        fileservice.mkdir(body["path"])
        return Response(status_code=201)
    except ValueError as e:
        return Response(status_code=400, content=str(e))


@app.post("/_platform/moves")
async def move(request: Request):
    body = await request.json()
    try:
        fileservice.move(body["src"], body["dst"])
        return {"status": "ok"}
    except ValueError as e:
        return Response(status_code=400, content=str(e))


@app.get("/_platform/me")
def me():
    return {"workspace_id": os.environ.get("HARNESS_WORKSPACE_ID"),
            "generation": int(os.environ.get("HARNESS_GENERATION", "0"))}


# ---- terminal WebSocket ----------------------------------------------------
@app.websocket("/_platform/terminal")
async def terminal(ws: WebSocket):
    await ws.accept()
    tid = os.urandom(8).hex()
    term = PTYSession()
    _terminals[tid] = term
    try:
        async def pump():
            while True:
                data = term.read(0.05)
                if data:
                    await ws.send_bytes(data)
                elif not term.alive():
                    await ws.send_json({"type": "exit", "code": term.proc.returncode})
                    break
                await asyncio.sleep(0)
        pump_task = asyncio.create_task(pump())
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            term.write(msg.get("bytes") or msg.get("text", "").encode())
        pump_task.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        code = term.close()
        _terminals.pop(tid, None)
        try:
            await ws.send_json({"type": "exit", "code": code})
        except Exception:
            pass


# ---- native dsh paths (last) -----------------------------------------------
@app.websocket("/{path:path}")
async def native_ws(path: str, websocket: WebSocket):
    # adapter.ws_proxy injects the dsh session cookie, exact Host and protocols.
    await adapter.ws_proxy(path, websocket)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def native(path: str, request: Request):
    return await adapter.proxy(path, request)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="warning")
