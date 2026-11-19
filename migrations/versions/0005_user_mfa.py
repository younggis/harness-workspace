"""TOTP MFA columns on users.

Revision ID: 0005_user_mfa
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_user_mfa"
down_revision = "0004_credential_hash_reissue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = [c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")]
    if "mfa_secret" not in cols:
        op.add_column("users", sa.Column("mfa_secret", sa.String(128), nullable=True))
    if "mfa_enabled" not in cols:
        op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "mfa_secret")
