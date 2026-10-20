"""Owner labels of what the right verdict was, to measure the judge

Revision ID: e6f708192031
Revises: d5e6f7081920
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f708192031"
down_revision: str | Sequence[str] | None = "d5e6f7081920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One label per result: what the owner says the verdict should have been. Compared with the
    # judge's own verdict to show how often it agrees.
    op.create_table(
        "judge_labels",
        sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scans.id"), primary_key=True),
        sa.Column("test_id", sa.Text(), primary_key=True),
        sa.Column("correct", sa.Text(), nullable=False),
        sa.Column("labeled_at", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("judge_labels")
