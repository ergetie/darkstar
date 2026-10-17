"""add pv_ml_residual_raw_kwh to slot_forecasts

Revision ID: c3a9e5d7b1f2
Revises: b7e2c4a9f1d3
Create Date: 2026-10-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9e5d7b1f2"
down_revision: str | Sequence[str] | None = "b7e2c4a9f1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "slot_forecasts"
COLUMN = "pv_ml_residual_raw_kwh"


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns(TABLE)]
    if COLUMN not in columns:
        op.add_column(TABLE, sa.Column(COLUMN, sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns(TABLE)]
    if COLUMN in columns:
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)
