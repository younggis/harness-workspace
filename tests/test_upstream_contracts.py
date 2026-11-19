"""Contract gate for upstream dsh upgrades.

These tests do NOT talk to the network: they validate that real, sanitized samples
exist and still match the contracts our adapter relies on. Re-capture with
scripts/capture_contracts.py + capture_session_contract.py against a candidate image.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "upstream"


def _load(name):
    p = CONTRACTS / name
    assert p.exists(), f"missing contract sample {name}"
    return json.loads(p.read_text(encoding="utf-8"))


def test_samples_are_real_and_sanitized():
    names = ["web-http.sanitized.json", "events-sse.sanitized.json",
             "web-ws.sanitized.json", "session-contract.sanitized.json"]
    for n in names:
        data = _load(n)
        assert data.get("captured") is True
        text = json.dumps(data, ensure_ascii=False)
        assert not re.search(r"sk-[A-Za-z0-9]{20,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)


def test_web_http_exchange_contract():
    d = _load("web-http.sanitized.json")
    assert d["exchange_status"] == 303
    assert d["exchange_location"] == "./"
    assert d["exchange_cookie_name"] == "harness_ws"
    assert d["root_status"] == 200
    assert "html" in d["root_content_type"]


def test_web_ws_contract():
    d = _load("web-ws.sanitized.json")
    assert d["path"] == "/api/remote.mux"
    assert isinstance(d["frames"], list)


def test_session_projection_contract():
    d = _load("session-contract.sanitized.json")
    rows = d["rows"]
    for key in ("modelSelection", "permissions", "tokenUsage", "turnBoundary", "sessionStats"):
        assert key in rows, f"missing projection row {key}"
        row = rows[key]
        assert "ver" in row and "seq" in row and "val" in row
    assert rows["permissions"]["val"]["approval"] in ("ask", "never")
    assert rows["modelSelection"]["val"]["lastUsed"]["model"] == "deepseek-flash"
    totals = rows["tokenUsage"]["val"]["totals"]
    assert all(k in totals for k in ("uncachedInputTokens", "outputTokens", "cacheReadTokens"))
