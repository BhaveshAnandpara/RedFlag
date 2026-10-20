"""the turns of a multi-turn attack on scan results

Revision ID: c4d5e6f70819
Revises: b2c3d4e5f607
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f70819"
down_revision: str | Sequence[str] | None = "b2c3d4e5f607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every turn of a multi-turn attack, as a list of {role, content}. Results of single-message
    # tests, and results saved before this, have none.
    op.add_column("scan_results", sa.Column("turns", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("scan_results", "turns")
