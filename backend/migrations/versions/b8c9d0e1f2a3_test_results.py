"""test results: the proof written for each run of a spec

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per finished test in a run. It points at the exact spec version and hash it tested.
    op.create_table(
        "test_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("spec_id", sa.Text(), nullable=False),
        sa.Column("spec_version", sa.Integer(), nullable=False),
        sa.Column("spec_hash", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("record", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_test_results_run", "test_results", ["run_id"])
    op.create_index("ix_test_results_spec", "test_results", ["spec_id", "created_at"])


def downgrade() -> None:
    op.drop_table("test_results")
