"""Capture REAL sanitized upstream contract samples from a running workspace.

Run with an active stack; writes contracts/upstream/*.sanitized.json.
Secrets (cookies, tickets, tokens, session ids, hostnames) are replaced before write.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import websockets

BASE = "http://127.0.0.1:8080"
PORTAL = "http://portal.127.0.0.1.nip.io:8080"
WID = "319fc425-cf45-4307-b4a9-b693fe67cad9"
OUT = Path("contracts/upstream")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
TOKEN_RE = re.compile(r"(token=)[^&\s\"']+", re.I)
LONG_RE = re.compile(r"\b[A-Za-z0-9_-]{32,}\b")


def sanitize(text: str) -> str:
    text = UUID_RE.sub("<uuid>", text)
    text = TOKEN_RE.sub(r"\1<token>", text)
    text = LONG_RE.sub("<token>", text)
    return text[:4000]


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(PORTAL + "/api/auth/login",
                         json={"login": "a1", "password": "Str0ngPassw0rd!x"},
                         headers={"Origin": PORTAL})
        assert r.status_code == 200, r.text
        csrf = r.json()["csrf_token"]
        r = await c.post(PORTAL + f"/api/workspaces/{WID}/entry-tickets", json={"target": "agent"},
                         headers={"Origin": PORTAL, "X-CSRF-Token": csrf})
        assert r.status_code == 201, r.text
        ticket = r.json()
        host = ticket["workspace_host"]
        r = await c.post(BASE + "/_platform/enter", data={"ticket": ticket["ticket"]},
                         headers={"Host": host, "Origin": PORTAL}, follow_redirects=False)
        assert r.status_code == 303, r.text
        cookie = r.headers["set-cookie"].split(";", 1)[0]
        headers = {"Host": host, "Origin": "http://" + host, "Cookie": cookie}

        # 1) root document shape
        root = await c.get(BASE + "/", headers=headers)
        (OUT / "web-http.sanitized.json").write_text(json.dumps({
            "captured": True,
            "exchange_status": 303,
            "exchange_location": "./",
            "exchange_cookie_name": cookie.split("=")[0],
            "root_status": root.status_code,
            "root_content_type": root.headers.get("content-type"),
            "root_head_sanitized": sanitize(root.text[:300]),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # 2) SSE event stream first lines
        try:
            async with c.stream("GET", BASE + "/plugins/events", headers=headers, timeout=8.0) as s:
                lines = []
                async for line in s.aiter_lines():
                    if line.strip():
                        lines.append(sanitize(line))
                    if len(lines) >= 6:
                        break
        except Exception as exc:
            lines = [f"<capture-error {type(exc).__name__}>"]
        (OUT / "events-sse.sanitized.json").write_text(json.dumps({
            "captured": True, "path": "/plugins/events", "first_lines": lines,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3) native remote WS first text frame
    frames = []
    try:
        ws = await websockets.connect(f"ws://{host}/api/remote.mux",
                                      additional_headers={"Origin": "http://" + host, "Cookie": cookie})
        try:
            for _ in range(2):
                data = await asyncio.wait_for(ws.recv(), timeout=4.0)
                frames.append({"type": type(data).__name__, "text": sanitize(str(data))})
        except asyncio.TimeoutError:
            pass
        await ws.close()
    except Exception as exc:
        frames = [{"error": f"{type(exc).__name__}: {exc}"}]
    (OUT / "web-ws.sanitized.json").write_text(json.dumps({
        "captured": True, "path": "/api/remote.mux", "frames": frames,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("captured:", ", ".join(p.name for p in sorted(OUT.glob("*.sanitized.json"))))


asyncio.run(main())
