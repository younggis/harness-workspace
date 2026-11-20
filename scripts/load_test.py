"""T17 load test: cold/hot starts x5 and 1/2/4-space concurrency.

Uses the real control-plane API. Restores original desired states at the end.
Run against a test installation only; it stops/starts real spaces.

Env: HARNESS_ADMIN_LOGIN / HARNESS_ADMIN_PASSWORD, HARNESS_BASE (default port 8080),
HARNESS_PORTAL_ORIGIN. Optional: LOAD_ITERATIONS, LOAD_IDLE_SECONDS.
"""
from __future__ import annotations

import json
import os
import statistics
import time

import httpx

BASE = os.environ.get("HARNESS_BASE", "http://127.0.0.1:8080")
ORIGIN = os.environ.get("HARNESS_PORTAL_ORIGIN", "http://portal.127.0.0.1.nip.io:8080")
LOGIN = os.environ.get("HARNESS_ADMIN_LOGIN", "admin")
PASSWORD = os.environ.get("HARNESS_ADMIN_PASSWORD", "")
ITERATIONS = int(os.environ.get("LOAD_ITERATIONS", "5"))
IDLE = float(os.environ.get("LOAD_IDLE_SECONDS", "5"))
POLL_TIMEOUT = 90.0


def main() -> None:
    if not PASSWORD:
        raise SystemExit("HARNESS_ADMIN_PASSWORD is required")
    with httpx.Client(base_url=BASE, timeout=15.0) as c:
        r = c.post("/api/auth/login", json={"login": LOGIN, "password": PASSWORD},
                   headers={"Origin": ORIGIN})
        r.raise_for_status()
        csrf = r.json()["csrf_token"]
        # The admin workbench lists only owned spaces; aggregate all tenants.
        tenants = c.get("/api/admin/tenants").json()["items"]
        spaces = []
        for t in tenants:
            spaces.extend(c.get(f"/api/admin/tenants/{t['id']}/workspaces").json()["items"])
        if len(spaces) < 4:
            raise SystemExit(f"need >=4 workspaces for T17, found {len(spaces)}")
        originals = {w["id"]: w["desired_state"] for w in spaces}
        ids = [w["id"] for w in spaces]
        print(f"workspaces={len(ids)} iterations={ITERATIONS} idle={IDLE}s")

        def hdr(key: str) -> dict:
            return {"Origin": ORIGIN, "X-CSRF-Token": csrf, "Idempotency-Key": key}

        def action(wid: str, act: str, key: str) -> None:
            rr = c.post(f"/api/workspaces/{wid}/actions/{act}", headers=hdr(key))
            if rr.status_code not in (202, 409):
                raise RuntimeError(f"{act} {wid}: {rr.status_code} {rr.text}")

        def observed(wid: str) -> str:
            rr = c.get(f"/api/workspaces/{wid}")
            rr.raise_for_status()
            return rr.json()["observed_state"]

        def wait_state(wid: str, target: str) -> float:
            t0 = time.monotonic()
            while time.monotonic() - t0 < POLL_TIMEOUT:
                if observed(wid) == target:
                    return round(time.monotonic() - t0, 2)
                time.sleep(0.7)
            raise TimeoutError(f"{wid} never reached {target}")

        results: dict = {"cold": [], "hot": [], "concurrency": {}}
        try:
            for i in range(ITERATIONS):
                for wid in ids[:4]:
                    action(wid, "stop", f"load-cold-stop-{i}-{wid}")
                    wait_state(wid, "stopped")
                    time.sleep(IDLE)
                    t0 = time.monotonic()
                    action(wid, "start", f"load-cold-start-{i}-{wid}")
                    wait_state(wid, "running")
                    results["cold"].append(round(time.monotonic() - t0, 2))
                for wid in ids[:4]:
                    action(wid, "stop", f"load-hot-stop-{i}-{wid}")
                    wait_state(wid, "stopped")
                    t0 = time.monotonic()
                    action(wid, "start", f"load-hot-start-{i}-{wid}")
                    wait_state(wid, "running")
                    results["hot"].append(round(time.monotonic() - t0, 2))
                print(f"iteration {i+1}/{ITERATIONS} done")

            for n in (1, 2, 4):
                batch = ids[:n]
                for wid in batch:
                    action(wid, "stop", f"load-conc-stop-{n}-{wid}")
                    wait_state(wid, "stopped")
                t0 = time.monotonic()
                for wid in batch:
                    action(wid, "start", f"load-conc-start-{n}-{wid}")
                for wid in batch:
                    wait_state(wid, "running")
                results["concurrency"][str(n)] = round(time.monotonic() - t0, 2)
        finally:
            for wid, state in originals.items():
                try:
                    act = "start" if state == "running" else "stop"
                    action(wid, act, f"load-restore-{wid}")
                except Exception as exc:
                    print(f"restore failed {wid}: {exc}")

        def stats(v):
            if not v:
                return {}
            return {"n": len(v), "avg": round(statistics.mean(v), 2),
                    "min": min(v), "max": max(v)}
        print("LOAD_TEST_PASS")
        print(json.dumps({"cold": stats(results["cold"]), "hot": stats(results["hot"]),
                          "concurrency": results["concurrency"]}, indent=2))


if __name__ == "__main__":
    main()
