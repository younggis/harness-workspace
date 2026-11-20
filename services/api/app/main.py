"""Control-plane API application."""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from harness_common.config import Settings, get_settings
from harness_common.db import make_engine, make_session_factory, ping
from harness_common.errors import APIError, api_error_handler, error_response

from . import routers
from .routers import oidc, mfa, scim, tokens
from .connections import ConnectionRegistry
from .ratelimit import LoginRateLimiter

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _portal_origins(settings: Settings) -> set[str]:
    origins = {settings.portal_origin}
    if settings.app_env == "development":
        # Local dev: the portal is also reachable by loopback IP (no DNS/hosts).
        origins.update({
            f"http://127.0.0.1:{settings.edge_port}",
            f"http://localhost:{settings.edge_port}",
        })
    return origins


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.app_database_url(), schema=settings.pg_schema)
    session_factory = make_session_factory(engine)
    registry = ConnectionRegistry(lambda: session_factory, redis_url=settings.redis_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        registry.start()
        try:
            yield
        finally:
            # Close live WS/SSE connections and stop the Redis listener so no
            # client is left hanging on a rolling restart.
            await registry.stop()

    app = FastAPI(title="Harness Control API", version="1.0.0",
                  docs_url="/docs", redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.connections = registry
    app.state.login_limiter = LoginRateLimiter(redis_url=settings.redis_url)

    app.add_exception_handler(APIError, api_error_handler)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
        request.state.started = time.monotonic()

        # Exact-Origin enforcement on state-changing browser requests.
        # No permissive credentialed CORS. Internal/health paths are server-to-server.
        if request.method in WRITE_METHODS and not request.url.path.startswith(("/internal", "/health", "/scim/")):
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if request.url.path == "/_platform/enter":
                # The single intentional portal -> workspace cross-host form POST.
                allowed = _portal_origins(settings)
            elif host.startswith("w-"):
                # Workspace host: portal APIs and native dsh /api/... all share
                # the browser's workspace-host Origin.
                allowed = {f"http://{host}"}
            else:
                allowed = _portal_origins(settings)
            if not origin or origin not in allowed:
                return error_response(
                    "FORBIDDEN", "Origin check failed", status=403, request_id=rid,
                )

        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        db_ok = ping(app.state.engine)
        return {
            "status": "ok" if db_ok else "degraded",
            "checks": {
                "db": "ok" if db_ok else "down",
                "engine": "not-required-in-api",
                "template_image": "configured",
                "runtime": "managed-by-worker",
                "model_probe": "not-required-in-api",
            },
        }

    app.include_router(routers.auth.router)
    app.include_router(routers.admin.router)
    app.include_router(routers.workspaces.router)
    # These must precede the gateway catch-all route, otherwise it swallows them.
    app.include_router(oidc.router)
    app.include_router(mfa.router)
    app.include_router(scim.router)
    app.include_router(tokens.router)
    app.include_router(routers.gateway.router)
    return app


app = create_app()
