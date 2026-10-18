"""baseline

Revision ID: ad7111bef358
Revises:
Create Date: 2026-10-18 18:12:44.867767

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "ad7111bef358"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
