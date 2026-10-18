"""llm spend

Revision ID: c3d4e5f60718
Revises: 8a2aa8f938a9
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f60718"
down_revision: str | Sequence[str] | None = "8a2aa8f938a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A single running total of estimated paid spend. It lives in the database so a restart
    # cannot reset the spending cap.
    op.create_table(
        "llm_spend",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("total_usd", sa.Float(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 1", name="llm_spend_single_row"),
    )


def downgrade() -> None:
    op.drop_table("llm_spend")
