"""add ev_charger_observations table

Per-charger recorded EV energy per slot (ev-per-charger-energy).

Revision ID: a3f5c7e9b1d2
Revises: b7d4e1f9a2c6
Create Date: 2026-09-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f5c7e9b1d2"
down_revision: str | Sequence[str] | None = "b7d4e1f9a2c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ev_charger_observations"


def upgrade() -> None:
    """Upgrade schema."""
    inspector = sa.inspect(op.get_bind())
    if TABLE in inspector.get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("slot_start", sa.String(), nullable=False),
        sa.Column("charger_id", sa.String(), nullable=False),
        sa.Column("energy_kwh", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("slot_start", "charger_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    inspector = sa.inspect(op.get_bind())
    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)
