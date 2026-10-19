"""the AI judge's output and the plain rules' own output on scan results

Revision ID: f60718293041
Revises: e5f607182930
Create Date: 2026-10-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f60718293041"
down_revision: str | Sequence[str] | None = "e5f607182930"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = (
    "rule_status",
    "rule_evidence",
    "judge_status",
    "judge_reason",
    "judge_model",
    "judge_provider",
)


def upgrade() -> None:
    # `status` and `evidence` keep holding the combined verdict, so everything that reads them is
    # unchanged. These keep each side's own output. Results saved before the judge have none.
    for name in COLUMNS:
        op.add_column("scan_results", sa.Column(name, sa.Text(), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("scan_results", name)
