"""test specs: the promise written for each test before a run, locked when the plan is approved

Revision ID: a7b8c9d0e1f2
Revises: e6f708192031
Create Date: 2026-10-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e6f708192031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One row per version of a spec. A locked version is never changed: a change adds the next one.
    op.create_table(
        "test_specs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("spec_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("spec_hash", sa.Text(), nullable=False),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("locked_at", sa.Float(), nullable=True),
        sa.UniqueConstraint("spec_id", "version", name="uq_test_specs_id_version"),
    )


def downgrade() -> None:
    op.drop_table("test_specs")
