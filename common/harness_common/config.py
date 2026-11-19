"""Environment-driven settings. Secrets are read from the process environment only.

Database URLs are built with SQLAlchemy's URL.create so passwords containing special
characters never need manual DSN escaping.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _env(name: str, default: str = "") -> str:
    """Read a setting, preferring a Docker/Kubernetes secret file when provided.

    If `<NAME>_FILE` points to a mounted file, its contents (trimmed) are used
    instead of the literal env var. This lets production inject secrets without
    placing them in the process environment or Compose file.
    """
    path = os.environ.get(name + "_FILE", "")
    if path and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            pass
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    app_env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    installation_id: str = field(default_factory=lambda: _env("INSTALLATION_ID", "harness-local-dev"))
    portal_origin: str = field(default_factory=lambda: _env("PORTAL_ORIGIN", "http://portal.localhost:8080"))
    workspace_host_suffix: str = field(default_factory=lambda: _env("WORKSPACE_HOST_SUFFIX", ".localhost:8080"))

    pg_host: str = field(default_factory=lambda: _env("PG_HOST", "127.0.0.1"))
    pg_port: int = field(default_factory=lambda: int(_env("PG_PORT", "5432")))
    pg_database: str = field(default_factory=lambda: _env("PG_DATABASE", "postgis"))
    pg_schema: str = field(default_factory=lambda: _env("PG_SCHEMA", "harness"))
    pg_app_user: str = field(default_factory=lambda: _env("PG_APP_USER", "harness_app"))
    pg_app_password: str = field(default_factory=lambda: _env("PG_APP_PASSWORD"))
    pg_migration_user: str = field(default_factory=lambda: _env("PG_MIGRATION_USER", "harness_owner"))
    pg_migration_password: str = field(default_factory=lambda: _env("PG_MIGRATION_PASSWORD"))
    pg_llm_user: str = field(default_factory=lambda: _env("PG_LLM_USER", "harness_llm"))
    pg_llm_password: str = field(default_factory=lambda: _env("PG_LLM_PASSWORD"))
    pg_test_schema: str = field(default_factory=lambda: _env("PG_TEST_SCHEMA", "harness_test"))

    deepseek_base_url: str = field(default_factory=lambda: _env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    deepseek_model: str = field(default_factory=lambda: _env("DEEPSEEK_MODEL", "deepseek-flash"))
    deepseek_api_key: str = field(default_factory=lambda: _env("DEEPSEEK_API_KEY"))
    reasoning_effort: str = field(default_factory=lambda: _env("REASONING_EFFORT", "high"))
    thinking_enabled: bool = field(default_factory=lambda: _env("THINKING_ENABLED", "true").lower() == "true")

    relay_signing_key: str = field(default_factory=lambda: _env("RELAY_SIGNING_KEY"))
    session_signing_key: str = field(default_factory=lambda: _env("SESSION_SIGNING_KEY"))
    workspace_token_seed: str = field(default_factory=lambda: _env("HARNESS_WORKSPACE_TOKEN_SEED"))

    # Enterprise identity (OIDC) and MFA
    oidc_issuer: str = field(default_factory=lambda: _env("OIDC_ISSUER"))
    oidc_client_id: str = field(default_factory=lambda: _env("OIDC_CLIENT_ID"))
    oidc_client_secret: str = field(default_factory=lambda: _env("OIDC_CLIENT_SECRET"))
    oidc_redirect_uri: str = field(default_factory=lambda: _env("OIDC_REDIRECT_URI"))
    oidc_auto_provision: bool = field(default_factory=lambda: _env("OIDC_AUTO_PROVISION", "false").lower() == "true")
    mfa_required: bool = field(default_factory=lambda: _env("MFA_REQUIRED", "false").lower() == "true")

    # Cross-process revocation for multi-replica API deployments.
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL"))

    dsh_version: str = field(default_factory=lambda: _env("DSH_VERSION", "0.2.2-rc.4"))
    edge_port: int = field(default_factory=lambda: int(_env("EDGE_PORT", "8080")))

    sqlite_path: str = field(default_factory=lambda: _env("HARNESS_SQLITE_PATH", ""))

    # ---- connection URL builders -------------------------------------------
    def _pg_url(self, user: str, password: str) -> str:
        from sqlalchemy.engine import URL
        url = URL.create(
            "postgresql+psycopg",
            username=user,
            password=password or None,
            host=self.pg_host,
            port=self.pg_port,
            database=self.pg_database,
        )
        return url.render_as_string(hide_password=False)

    def app_database_url(self) -> str:
        return self.sqlite_path or self._pg_url(self.pg_app_user, self.pg_app_password)

    def migration_database_url(self) -> str:
        return self._pg_url(self.pg_migration_user, self.pg_migration_password)

    def llm_database_url(self) -> str:
        return self._pg_url(self.pg_llm_user, self.pg_llm_password)

    def workspace_host(self, workspace_id: str) -> str:
        return f"w-{workspace_id}{self.workspace_host_suffix}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
