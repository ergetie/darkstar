"""add slot_end to slot_plans

Revision ID: b7d4e1f9a2c6
Revises: c5e8d2a7f913
Create Date: 2026-09-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4e1f9a2c6"
down_revision: str | Sequence[str] | None = "c5e8d2a7f913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "slot_plans" in tables:
        columns = [c["name"] for c in inspector.get_columns("slot_plans")]
        if "slot_end" not in columns:
            op.add_column(
                "slot_plans",
                sa.Column("slot_end", sa.String(), nullable=True),
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "slot_plans" in tables:
        columns = [c["name"] for c in inspector.get_columns("slot_plans")]
        if "slot_end" in columns:
            with op.batch_alter_table("slot_plans", schema=None) as batch_op:
                batch_op.drop_column("slot_end")
