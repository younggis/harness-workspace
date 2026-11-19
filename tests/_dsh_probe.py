"""Manual probe: native dsh Web HTTP + WS through the platform gateway."""
import asyncio

import httpx
import websockets

BASE = "http://127.0.0.1:8080"
PORTAL = "http://portal.127.0.0.1.nip.io:8080"
WID = "319fc425-cf45-4307-b4a9-b693fe67cad9"


async def main():
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(PORTAL + "/api/auth/login", json={"login": "a1", "password": "Str0ngPassw0rd!x"},
                         headers={"Origin": PORTAL})
        assert r.status_code == 200, r.text
        csrf = r.json()["csrf_token"]
        r = await c.post(PORTAL + f"/api/workspaces/{WID}/entry-tickets", json={"target": "agent"},
                         headers={"Origin": PORTAL, "X-CSRF-Token": csrf})
        assert r.status_code == 201, r.text
        j = r.json()
        host = j["workspace_host"]
        r = await c.post(BASE + "/_platform/enter", data={"ticket": j["ticket"]},
                         headers={"Host": host, "Origin": PORTAL}, follow_redirects=False)
        assert r.status_code == 303, r.text
        cookie = r.headers["set-cookie"].split(";", 1)[0]

        # HTTP: root page + a native dsh API call
        root = await c.get(BASE + "/", headers={"Host": host, "Origin": "http://" + host, "Cookie": cookie})
        print("ROOT:", root.status_code, "dsh html:", "DeepSeek Harness".lower() in root.text.lower())
        api = await c.post(BASE + "/api/dynamicCordisRunner/inventory", json={},
                           headers={"Host": host, "Origin": "http://" + host, "Cookie": cookie})
        print("DSH API:", api.status_code, api.text[:120])

    # WS: native dsh remote.mux
    try:
        ws = await websockets.connect(f"ws://{host}/api/remote.mux",
                                      additional_headers={"Origin": "http://" + host, "Cookie": cookie})
        print("DSH WS: connected")
        await ws.close()
    except Exception as exc:
        print("DSH WS FAILED:", type(exc).__name__, str(exc)[:200])


asyncio.run(main())
