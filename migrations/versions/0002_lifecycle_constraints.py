"""Lifecycle constraints: one active op per workspace, one active credential per generation.

Revision ID: 0002_lifecycle_constraints
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_lifecycle_constraints"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove duplicates that older reconciliation races may have created.
    op.execute("""
        UPDATE workspace_operations SET state='failed', finished_at=now(),
               error_code='SUPERSEDED_BY_CONSTRAINT'
        WHERE state IN ('queued','running') AND id NOT IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY workspace_id ORDER BY created_at
                ) AS rn FROM workspace_operations
                WHERE state IN ('queued','running')
            ) t WHERE rn = 1
        )
    """)
    op.execute("""
        UPDATE runtime_credentials SET revoked_at=now()
        WHERE revoked_at IS NULL AND id NOT IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (
                    PARTITION BY workspace_id, generation ORDER BY created_at DESC
                ) AS rn FROM runtime_credentials
                WHERE revoked_at IS NULL
            ) t WHERE rn = 1
        )
    """)
    # 0001's create_all may already have emitted these indexes from model metadata.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_op_active_ws
        ON workspace_operations (workspace_id) WHERE state IN ('queued','running')
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_credential_active
        ON runtime_credentials (workspace_id, generation) WHERE revoked_at IS NULL
    """)


def downgrade() -> None:
    op.drop_index("uq_credential_active", table_name="runtime_credentials")
    op.drop_index("uq_op_active_ws", table_name="workspace_operations")
