"""drop dead schedule_planned table

Revision ID: 8dfd5256374c
Revises: c3a7e5f19b2d
Create Date: 2026-07-06 09:06:06.865036

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8dfd5256374c"
down_revision: str | Sequence[str] | None = "c3a7e5f19b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("schedule_planned")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "schedule_planned",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("planned_kwh", sa.Float(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_schedule_planned_date"), "schedule_planned", ["date"], unique=False)
