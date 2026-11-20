"""Model proxy.

- Validates a short-lived workspace token (hash compared against runtime_credentials).
- Fixed upstream DeepSeek base URL; configured OpenAI Chat Completions protocol.
- Streams SSE chunks unchanged (reasoning_content, content, tool deltas, usage, [DONE]).
- Reserves a conservative budget in a DB transaction before calling upstream, then
  settles with real usage. Unauthorized models / external URLs are rejected.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from harness_common.config import get_settings
from harness_common.metrics import Metrics
from harness_common.db import make_engine, make_session_factory
from harness_common.errors import APIError, api_error_handler, error_response
from harness_common.security import token_hash

settings = get_settings()
app = FastAPI(title="Harness Model Proxy")
app.add_exception_handler(APIError, api_error_handler)
engine = make_engine(settings.llm_database_url(), schema=settings.pg_schema)
factory = make_session_factory(engine)
metrics = Metrics("harness_llm_")
ALLOWED_MODELS = {settings.deepseek_model}
UPSTREAM = settings.deepseek_base_url.rstrip("/")
RESERVE_UNITS = 8192  # conservative input+output upper bound for hard budget
FIRST_BYTE_TIMEOUT = float(os.environ.get("MODEL_FIRST_BYTE_TIMEOUT", "30"))
READ_IDLE_TIMEOUT = float(os.environ.get("MODEL_READ_IDLE_TIMEOUT", "120"))
MAX_UPSTREAM_ATTEMPTS = 3
TOTAL_TIMEOUT = float(os.environ.get("MODEL_TOTAL_TIMEOUT", "600"))
MAX_CONCURRENT = int(os.environ.get("MODEL_MAX_CONCURRENT", "8"))

# One pooled client for the process: TLS handshakes to DeepSeek are reused
# instead of renegotiated for every request (avg latency reduction).
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()
_concurrency = asyncio.Semaphore(MAX_CONCURRENT)


async def _upstream_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        async with _client_lock:
            if _client is None or _client.is_closed:
                _client = httpx.AsyncClient(
                    timeout=httpx.Timeout(TOTAL_TIMEOUT, connect=FIRST_BYTE_TIMEOUT,
                                          read=READ_IDLE_TIMEOUT),
                    limits=httpx.Limits(max_connections=MAX_CONCURRENT * 2,
                                        max_keepalive_connections=MAX_CONCURRENT),
                )
    return _client


def _auth(request: Request) -> tuple[str, str, int]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise APIError("UNAUTHENTICATED", "Workspace model token required")
    token = header[7:].strip()
    with factory() as db:
        from sqlalchemy import text
        row = db.execute(text(
            "SELECT workspace_id, generation FROM runtime_credentials "
            "WHERE token_hash = :h AND revoked_at IS NULL AND expires_at > now()"
        ), {"h": token_hash(token)}).first()
        if not row:
            raise APIError("UNAUTHENTICATED", "Invalid workspace model token")
        return str(row[0]), str(row[1]), token


@app.get("/v1/models")
def models(request: Request):
    _auth(request)
    return {"object": "list", "data": [
        {"id": m, "object": "model", "owned_by": "deepseek"} for m in sorted(ALLOWED_MODELS)
    ]}


def _reserve(request_id: str, tenant_id: str, ws_id: str, model: str) -> None:
    metrics.inc("model_requests_total", {"model": model, "state": "started"})
    from sqlalchemy import text
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with factory() as db:
        db.execute(text(
            "INSERT INTO budget_buckets(tenant_id,day,reserved,consumed) "
            "VALUES(:t,:d,:r,0) ON CONFLICT (tenant_id,day) DO NOTHING"
        ), {"t": tenant_id, "d": day, "r": RESERVE_UNITS})
        db.execute(text(
            "UPDATE budget_buckets SET reserved=reserved+:r WHERE tenant_id=:t AND day=:d"
        ), {"t": tenant_id, "d": day, "r": RESERVE_UNITS})
        db.execute(text(
            "INSERT INTO model_requests(request_id,tenant_id,workspace_id,model,state,reserved_units,usage_source,created_at) "
            "VALUES(:r,:t,:w,:m,'running',:u,'conservative',now()) "
            "ON CONFLICT (request_id) DO NOTHING"
        ), {"r": request_id, "t": tenant_id, "w": ws_id, "m": model, "u": RESERVE_UNITS})
        db.commit()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    ws_id, generation, token = _auth(request)
    try:
        body = await request.json()
    except Exception:
        raise APIError("CONFLICT", "Invalid JSON body")
    model = body.get("model")
    if model not in ALLOWED_MODELS:
        raise APIError("FORBIDDEN", "Model not allowed for this workspace")
    # derive tenant from the workspace (server-side credential context)
    from sqlalchemy import text
    with factory() as db:
        tenant = db.execute(text("SELECT tenant_id FROM workspaces WHERE id=:w"), {"w": ws_id}).scalar_one_or_none()
    if not tenant:
        raise APIError("UNAUTHENTICATED", "Unknown workspace")
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    _reserve(request_id, str(tenant), ws_id, model)

    upstream_body = {
        k: v for k, v in body.items()
        if k not in ("api_key", "authorization", "base_url")
    }
    upstream_body["model"] = settings.deepseek_model
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    wants_stream = bool(body.get("stream"))

    async def stream():
        start = time.monotonic()
        usage_seen = False
        try:
            for attempt in range(MAX_UPSTREAM_ATTEMPTS):
                try:
                  async with _concurrency:
                    client = await _upstream_client()
                    async with client.stream("POST", f"{UPSTREAM}/chat/completions", json=upstream_body, headers=headers) as resp:
                        if resp.status_code >= 400:
                            code = "UPSTREAM_ERROR"
                            if resp.status_code in (401, 403):
                                code = "FORBIDDEN"
                            elif resp.status_code == 429:
                                code = "RATE_LIMITED"
                            yield f"data: {json.dumps({'error': {'code': code, 'message': 'model upstream error', 'request_id': request_id}})}\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                yield "data: [DONE]\n\n"
                                continue
                            try:
                                obj = json.loads(payload)
                            except Exception:
                                continue
                            if obj.get("usage"):
                                usage_seen = True
                                _settle(request_id, obj["usage"], latency_ms=int((time.monotonic() - start) * 1000))
                            yield f"data: {json.dumps(obj, separators=(',', ':'))}\n\n"
                        return  # stream completed
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                    print(f"[llm] upstream attempt {attempt+1} failed: {type(exc).__name__}", flush=True)
                    if attempt == MAX_UPSTREAM_ATTEMPTS - 1:
                        raise
                    await asyncio.sleep(1 + attempt)
        except Exception as exc:
            import traceback
            print(f"[llm] stream interrupted request={request_id}: {type(exc).__name__}: {exc}", flush=True)
            traceback.print_exc()
            yield f"data: {json.dumps({'error': {'code': 'UPSTREAM_ERROR', 'message': 'stream interrupted', 'request_id': request_id}})}\n\n"
        finally:
            if not usage_seen:
                _settle_unknown(request_id, int((time.monotonic() - start) * 1000))

    if wants_stream:
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    # Non-streaming: collect the single JSON response, settle usage, return.
    t0 = time.monotonic()
    async with _concurrency:
        client = await _upstream_client()
        resp = await client.post(f"{UPSTREAM}/chat/completions", json=upstream_body, headers=headers)
    latency_ms = int((time.monotonic() - t0) * 1000)
    if resp.status_code >= 400:
        _settle_unknown(request_id, latency_ms)
        code = {401: "FORBIDDEN", 403: "FORBIDDEN", 429: "RATE_LIMITED"}.get(resp.status_code, "UPSTREAM_ERROR")
        return error_response(code, "model upstream error", status=502, request_id=request_id)
    obj = resp.json()
    _settle(request_id, obj.get("usage"), latency_ms=latency_ms)
    return JSONResponse(obj)


def _settle(request_id: str, usage: dict | None, *, latency_ms: int) -> None:
    metrics.inc("model_requests_total", {"state": "succeeded"})
    metrics.inc("model_tokens_total", {"kind": "input"}, value=(usage or {}).get("prompt_tokens") or 0)
    metrics.inc("model_tokens_total", {"kind": "output"}, value=(usage or {}).get("completion_tokens") or 0)
    from sqlalchemy import text
    source = "provider" if usage else "unknown"
    inp = (usage or {}).get("prompt_tokens")
    out = (usage or {}).get("completion_tokens")
    with factory() as db:
        db.execute(text(
            "UPDATE model_requests SET state='succeeded', input_tokens=:i, output_tokens=:o, "
            "usage_source=:s, latency_ms=:l, finished_at=now() WHERE request_id=:r"
        ), {"i": inp, "o": out, "s": source, "l": latency_ms, "r": request_id})
        if usage:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            # find tenant via request row
            t = db.execute(text("SELECT tenant_id FROM model_requests WHERE request_id=:r"), {"r": request_id}).scalar()
            db.execute(text(
                "UPDATE budget_buckets SET consumed=consumed+:c, reserved=GREATEST(0,reserved-:r) "
                "WHERE tenant_id=:t AND day=:d"
            ), {"c": (inp or 0) + (out or 0), "r": RESERVE_UNITS, "t": t, "d": day})
        db.commit()


def _settle_unknown(request_id: str, latency_ms: int) -> None:
    metrics.inc("model_requests_total", {"state": "unknown_usage"})
    from sqlalchemy import text
    with factory() as db:
        db.execute(text(
            "UPDATE model_requests SET state='succeeded', usage_source='unknown', latency_ms=:l, "
            "finished_at=now() WHERE request_id=:r AND state='running'"
        ), {"l": latency_ms, "r": request_id})
        db.commit()


@app.get("/metrics", include_in_schema=False)
def metrics_endpoint():
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/health/live")
def live():
    return {"status": "ok"}
