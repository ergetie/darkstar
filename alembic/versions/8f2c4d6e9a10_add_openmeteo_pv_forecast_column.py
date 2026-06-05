"""add openmeteo pv forecast column

Revision ID: 8f2c4d6e9a10
Revises: 65db61e6fcae
Create Date: 2026-06-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f2c4d6e9a10"
down_revision: str | Sequence[str] | None = "65db61e6fcae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("slot_forecasts")]

    if "openmeteo_pv_forecast_kwh" not in columns:
        op.add_column(
            "slot_forecasts",
            sa.Column("openmeteo_pv_forecast_kwh", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("slot_forecasts", "openmeteo_pv_forecast_kwh")
