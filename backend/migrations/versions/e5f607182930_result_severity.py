"""severity and fix note on scan results

Revision ID: e5f607182930
Revises: d4e5f6071829
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f607182930"
down_revision: str | Sequence[str] | None = "d4e5f6071829"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Saved with each result when the scan runs, so a result stays a faithful record even if
    # the test library changes later. Results saved before this have neither.
    op.add_column("scan_results", sa.Column("severity", sa.Text(), nullable=True))
    op.add_column("scan_results", sa.Column("remediation", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_results", "remediation")
    op.drop_column("scan_results", "severity")
