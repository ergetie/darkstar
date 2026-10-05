"""add known_prices_until to price_forecasts

Revision ID: d2a6f1c8e4b7
Revises: a3f5c7e9b1d2
Create Date: 2026-10-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a6f1c8e4b7"
down_revision: str | Sequence[str] | None = "a3f5c7e9b1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "price_forecasts" in tables:
        columns = [c["name"] for c in inspector.get_columns("price_forecasts")]
        if "known_prices_until" not in columns:
            op.add_column(
                "price_forecasts",
                sa.Column("known_prices_until", sa.String(), nullable=True),
            )


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "price_forecasts" in tables:
        columns = [c["name"] for c in inspector.get_columns("price_forecasts")]
        if "known_prices_until" in columns:
            with op.batch_alter_table("price_forecasts", schema=None) as batch_op:
                batch_op.drop_column("known_prices_until")
