"""Headless OIDC end-to-end check against scripts/mock_idp.py + oidc_e2e_server.py.

Run both servers first (see scripts/oidc-e2e.ps1), then:
    python scripts/oidc-e2e-check.py
Prints OIDC_E2E_PASS on success.
"""
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "common")):
    if p not in sys.path:
        sys.path.insert(0, p)

API = "http://127.0.0.1:9101"
with httpx.Client(follow_redirects=True, timeout=15.0) as c:
    cfg = c.get(f"{API}/api/auth/oidc/config").json()
    assert cfg["enabled"] is True, cfg
    r = c.get(f"{API}/api/auth/oidc/start")
    assert r.status_code in (200, 404), r.status_code  # ends at SPA-less "/"
    me = c.get(f"{API}/api/me")
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["user"]["login_norm"] == "oidc.e2e@example.com", body
    assert body["user"]["display_name"] == "OIDC E2E User", body
    print("OIDC_E2E_PASS", body["user"]["login_norm"])
