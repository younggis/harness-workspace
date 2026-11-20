"""Temporary API instance for OIDC E2E (isolated SQLite DB, real OIDC code path)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import uvicorn

DB = Path(tempfile.gettempdir()) / "harness-oidc-e2e.db"
# Routers resolve Settings via get_settings() (env-based), so configure env too.
os.environ.update({
    "HARNESS_SQLITE_PATH": f"sqlite:///{DB}",
    "PG_SCHEMA": "main",
    "PORTAL_ORIGIN": "http://127.0.0.1:9101",
    "WORKSPACE_HOST_SUFFIX": ".127.0.0.1:9101",
    "RELAY_SIGNING_KEY": "oidc-e2e-relay",
    "SESSION_SIGNING_KEY": "oidc-e2e-session",
    "OIDC_ISSUER": "http://127.0.0.1:9100",
    "OIDC_CLIENT_ID": "harness",
    "OIDC_REDIRECT_URI": "http://127.0.0.1:9101/api/auth/oidc/callback",
    "OIDC_AUTO_PROVISION": "true",
})

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "common")):
    if p not in sys.path:
        sys.path.insert(0, p)

from harness_common import models as m  # noqa: E402
from harness_common.config import Settings  # noqa: E402
from harness_common.db import make_engine, make_session_factory  # noqa: E402
from services.api.app.main import create_app  # noqa: E402

settings = Settings(
    sqlite_path=f"sqlite:///{DB}", pg_schema="main",
    portal_origin="http://127.0.0.1:9101",
    workspace_host_suffix=".127.0.0.1:9101",
    relay_signing_key="oidc-e2e-relay",
    session_signing_key="oidc-e2e-session",
    oidc_issuer="http://127.0.0.1:9100",
    oidc_client_id="harness",
    oidc_redirect_uri="http://127.0.0.1:9101/api/auth/oidc/callback",
    oidc_auto_provision=True,
)
app = create_app(settings)
engine = make_engine(settings.sqlite_path)
m.Base.metadata.create_all(engine)
app.state.engine = engine
app.state.session_factory = make_session_factory(engine)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9101, log_level="warning")
