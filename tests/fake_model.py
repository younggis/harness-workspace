"""Offline fake model: same /v1 surface as the proxy, deterministic scripts.

Never used for live conclusions. Drives chunked reasoning, chunked tool args,
a tool result, a final JSON answer, usage, and injectable 401/429/timeout/interrupt.
"""
from __future__ import annotations

import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Harness Fake Model")
SCENARIO = os.environ.get("FAKE_MODEL_SCENARIO", "ok")

CHUNKS = [
    {"delta": {"role": "assistant", "reasoning_content": "I need to count "}},
    {"delta": {"reasoning_content": "features and compute a bbox."}},
    {"delta": {"content": "Analyzing points.geojson with standard library. "}},
    {"delta": {"tool_calls": [{"index": 0, "id": "call_test_1", "type": "function",
                               "function": {"name": "run_python", "arguments": "{\"code\":"}}]}},
    {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "\"import json\\nprint('ok')\"}"}}]}},
]


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": "deepseek-flash", "object": "model", "owned_by": "deepseek"}]}


@app.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    if SCENARIO == "401":
        return JSONResponse({"error": {"message": "auth"}}, status_code=401)
    if SCENARIO == "429":
        return JSONResponse({"error": {"message": "rate"}}, status_code=429)
    if SCENARIO == "timeout":
        time.sleep(5)
    if not body.get("stream"):
        return {
            "id": "fake-req-1", "object": "chat.completion", "model": "deepseek-flash",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": '{"count":3}'}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        }

    async def gen():
        for c in CHUNKS:
            await _tick()
            yield _sse({"id": "fake-req-1", "object": "chat.completion.chunk",
                        "model": "deepseek-flash", "choices": [{"index": 0, "delta": c["delta"],
                                                               "finish_reason": None}]})
        yield _sse({"id": "fake-req-1", "choices": [{"index": 0, "delta": {},
                                                   "finish_reason": "tool_calls"}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}})
        if SCENARIO == "interrupt":
            return  # no [DONE]
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


async def _tick():
    import asyncio
    await asyncio.sleep(0.05)


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, separators=(',', ':'))}\n\n"
