"""Allow a deterministic token hash to be reissued after revocation.

Revision ID: 0004_credential_hash_reissue
"""
from __future__ import annotations

from alembic import op

revision = "0004_credential_hash_reissue"
down_revision = "0003_template_dsh_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The partial unique index uq_credential_active already enforces one active
    # token per (workspace, generation). A UNIQUE index on token_hash prevents
    # reissuing the same deterministic token after a stop revoked it.
    op.drop_index("ix_runtime_credentials_token_hash", table_name="runtime_credentials")
    op.create_index("ix_runtime_credentials_token_hash", "runtime_credentials", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_runtime_credentials_token_hash", table_name="runtime_credentials")
    op.create_index("ix_runtime_credentials_token_hash", "runtime_credentials", ["token_hash"], unique=True)
