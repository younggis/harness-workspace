"""Tenant-declared container resource policy (CPU/RAM/PIDS, no GPU).

Revision ID: 0007_tenant_resources
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_tenant_resources"
down_revision = "0006_api_tokens"
branch_labels = None
depends_on = None

GIB = 1024 ** 3


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch:
        batch.add_column(sa.Column("cpu_per_space", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("memory_per_space_bytes", sa.BigInteger(), nullable=False,
                                   server_default=str(GIB)))
        batch.add_column(sa.Column("pids_per_space", sa.Integer(), nullable=False, server_default="256"))
        batch.add_column(sa.Column("max_total_cpu", sa.Integer(), nullable=False, server_default="4"))
        batch.add_column(sa.Column("max_total_memory_bytes", sa.BigInteger(), nullable=False,
                                   server_default=str(4 * GIB)))
        batch.add_column(sa.Column("max_total_pids", sa.Integer(), nullable=False, server_default="1024"))

    # Existing spaces keep "inherit from template" semantics (NULL).
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(sa.Column("cpu", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("memory_bytes", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("pids_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("pids_limit")
        batch.drop_column("memory_bytes")
        batch.drop_column("cpu")
    with op.batch_alter_table("tenants") as batch:
        batch.drop_column("max_total_pids")
        batch.drop_column("max_total_memory_bytes")
        batch.drop_column("max_total_cpu")
        batch.drop_column("pids_per_space")
        batch.drop_column("memory_per_space_bytes")
        batch.drop_column("cpu_per_space")
