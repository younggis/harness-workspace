"""Track the pinned upstream dsh release on each immutable template.

Revision ID: 0003_template_dsh_version
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_template_dsh_version"
down_revision = "0002_lifecycle_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("templates", sa.Column("dsh_version", sa.String(64), nullable=True))
    op.execute("UPDATE templates SET dsh_version = '0.2.2-rc.4' WHERE dsh_version IS NULL")


def downgrade() -> None:
    op.drop_column("templates", "dsh_version")
