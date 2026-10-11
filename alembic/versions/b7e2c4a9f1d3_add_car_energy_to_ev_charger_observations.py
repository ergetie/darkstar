"""add car_energy_kwh and car_energy_source to ev_charger_observations

Revision ID: b7e2c4a9f1d3
Revises: d2a6f1c8e4b7
Create Date: 2026-10-11 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e2c4a9f1d3"
down_revision: str | Sequence[str] | None = "d2a6f1c8e4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ev_charger_observations"
NEW_COLUMNS = (
    ("car_energy_kwh", sa.Float()),
    ("car_energy_source", sa.String()),
)


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns(TABLE)]
    for name, col_type in NEW_COLUMNS:
        if name not in columns:
            op.add_column(TABLE, sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns(TABLE)]
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for name, _ in NEW_COLUMNS:
            if name in columns:
                batch_op.drop_column(name)
