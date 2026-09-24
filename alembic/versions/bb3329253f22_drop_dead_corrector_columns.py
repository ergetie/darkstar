"""drop dead corrector columns from slot_forecasts

Revision ID: bb3329253f22
Revises: b7c9d1e2f3a4
Create Date: 2026-09-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bb3329253f22"
down_revision: str | Sequence[str] | None = "b7c9d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEAD_COLUMNS = ("pv_correction_kwh", "load_correction_kwh", "correction_source")


def upgrade() -> None:
    """Drop the corrector columns that are present in this database."""
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("slot_forecasts")}
    to_drop = [col for col in DEAD_COLUMNS if col in existing]
    if not to_drop:
        return
    with op.batch_alter_table("slot_forecasts") as batch_op:
        for col in to_drop:
            batch_op.drop_column(col)


def downgrade() -> None:
    """Re-add the corrector columns with their original defaults (values are not restored)."""
    with op.batch_alter_table("slot_forecasts") as batch_op:
        batch_op.add_column(
            sa.Column("pv_correction_kwh", sa.Float(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column(
                "load_correction_kwh", sa.Float(), nullable=False, server_default=sa.text("0")
            )
        )
        batch_op.add_column(
            sa.Column(
                "correction_source", sa.String(), nullable=False, server_default=sa.text("'none'")
            )
        )
