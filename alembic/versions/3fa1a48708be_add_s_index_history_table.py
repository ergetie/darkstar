"""add s_index_history table

Revision ID: 3fa1a48708be
Revises: 8dfd5256374c
Create Date: 2026-07-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3fa1a48708be"
down_revision: str | Sequence[str] | None = "8dfd5256374c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "s_index_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_s_index_history_created_at", "s_index_history", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_s_index_history_created_at", table_name="s_index_history")
    op.drop_table("s_index_history")
