"""projects, scans and scan results

Revision ID: d4e5f6071829
Revises: c3d4e5f60718
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6071829"
down_revision: str | Sequence[str] | None = "c3d4e5f60718"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # One project per registered bot, made the first time the bot is scanned.
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
    )
    # The scan id is the scan number: one sequence for the whole system.
    op.create_table(
        "scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),  # running | completed | interrupted
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("finished_at", sa.Float(), nullable=True),
        sa.Column("last_progress_at", sa.Float(), nullable=False),
    )
    op.create_index("ix_scans_project_id", "scans", ["project_id"])
    op.create_table(
        "scan_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scan_id", sa.Integer(), sa.ForeignKey("scans.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("test_id", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        # pass | fail | inconclusive | error | not_applicable
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("attempts", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.Float(), nullable=False),
        sa.Column("finished_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("scan_id", "test_id", name="uq_scan_results_scan_test"),
    )


def downgrade() -> None:
    op.drop_table("scan_results")
    op.drop_index("ix_scans_project_id", table_name="scans")
    op.drop_table("scans")
    op.drop_table("projects")
