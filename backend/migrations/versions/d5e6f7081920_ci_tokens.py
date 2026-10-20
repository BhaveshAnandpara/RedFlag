"""API tokens for CI runs of one setup

Revision ID: d5e6f7081920
Revises: c4d5e6f70819
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7081920"
down_revision: str | Sequence[str] | None = "c4d5e6f70819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A token lets a build start runs of one setup and read their results. Only a hash of it is
    # kept, so a database copy cannot be used to start a run. The token itself is shown once.
    op.create_table(
        "ci_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("setup_id", sa.Integer(), sa.ForeignKey("setup_drafts.id"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("last_used_at", sa.Float(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_ci_tokens_setup_id", "ci_tokens", ["setup_id"])


def downgrade() -> None:
    op.drop_table("ci_tokens")
