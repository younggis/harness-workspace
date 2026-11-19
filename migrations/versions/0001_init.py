"""Initial schema for the harness platform (harness schema only).

Revision ID: 0001_init
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    "users", "tenants", "memberships", "auth_sessions", "templates", "workspaces",
    "workspace_operations", "entry_tickets", "workspace_sessions", "runtime_credentials",
    "model_requests", "budget_buckets", "audit_events",
]


def upgrade() -> None:
    # Tables are created by Alembic autogenerate-free explicit ops via Base.metadata
    # to keep this migration self-contained and schema-scoped.
    from harness_common.models import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables[t] for t in TABLES])

    # Least-privilege grants. Never grant to PUBLIC.
    app = "harness_app"
    llm = "harness_llm"
    business_dml = [t for t in TABLES if t not in ("model_requests", "budget_buckets")]
    for t in business_dml:
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{t}" TO {app}')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "model_requests" TO {llm}')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "budget_buckets" TO {llm}')
    op.execute(f'GRANT SELECT ON "tenants", "workspaces", "runtime_credentials" TO {llm}')


def downgrade() -> None:
    from harness_common.models import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=[Base.metadata.tables[t] for t in reversed(TABLES)])
