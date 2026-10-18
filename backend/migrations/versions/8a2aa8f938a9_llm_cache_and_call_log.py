"""llm cache and call log

Revision ID: 8a2aa8f938a9
Revises: ad7111bef358
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8a2aa8f938a9"
down_revision: str | Sequence[str] | None = "ad7111bef358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Saved answers. Times are epoch seconds so the app clock (and tests) control expiry.
    op.create_table(
        "llm_cache",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
    )
    op.create_index("ix_llm_cache_created_at", "llm_cache", ["created_at"])

    # One row per attempt, so every provider switch is on record.
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_created_at", table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index("ix_llm_cache_created_at", table_name="llm_cache")
    op.drop_table("llm_cache")
