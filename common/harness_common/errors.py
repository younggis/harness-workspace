"""Uniform API error envelope shared by FastAPI services."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


ERROR_STATUS = {
    "UNAUTHENTICATED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "VERSION_CONFLICT": 412,
    "PAYLOAD_TOO_LARGE": 413,
    "RATE_LIMITED": 429,
    "WORKSPACE_NOT_READY": 409,
    "UPSTREAM_ERROR": 502,
    "UNAVAILABLE": 503,
}


class APIError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None,
                 retryable: bool = False, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.status = status or ERROR_STATUS.get(code, 400)
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)


def error_response(code: str, message: str, *, status: int | None = None,
                   request_id: str | None = None, retryable: bool = False,
                   details: dict[str, Any] | None = None) -> JSONResponse:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id or str(uuid.uuid4()),
            "retryable": retryable,
        }
    }
    if details:
        payload["error"]["details"] = details
    return JSONResponse(status_code=status or ERROR_STATUS.get(code, 400), content=payload)


async def api_error_handler(_request: Request, exc: APIError) -> JSONResponse:
    rid = getattr(_request.state, "request_id", None)
    return error_response(exc.code, exc.message, status=exc.status,
                          request_id=rid, retryable=exc.retryable, details=exc.details)
