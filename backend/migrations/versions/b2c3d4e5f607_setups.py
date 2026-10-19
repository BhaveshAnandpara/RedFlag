"""setup drafts and versions for testing a user's own bot

Revision ID: b2c3d4e5f607
Revises: f60718293041
Create Date: 2026-10-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2c3d4e5f607"
down_revision: str | Sequence[str] | None = "f60718293041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A draft is what the owner is telling Redflag about a bot. It holds chat history, fields,
    # the endpoint settings (never the key) and the two contexts, and is edited in place.
    op.create_table(
        "setup_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
    )
    # A confirmed copy of a draft. Numbered per project and never changed afterwards.
    op.create_table(
        "setup_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("project_id", "number", name="uq_setup_versions_project_number"),
    )
    # The tests generated for a version, and which of them the owner ticked.
    op.create_table(
        "generated_tests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("setup_versions.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("test", postgresql.JSONB(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("version_id", "position", name="uq_generated_tests_position"),
    )
    # Which setup version a scan ran with. Scans of the demo bots and older scans have none.
    op.add_column(
        "scans",
        sa.Column("setup_version_id", sa.Integer(), sa.ForeignKey("setup_versions.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scans", "setup_version_id")
    op.drop_table("generated_tests")
    op.drop_table("setup_versions")
    op.drop_table("setup_drafts")
