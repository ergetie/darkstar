"""add planned_ev_charging_kwh to slot_plans

Revision ID: c5e8d2a7f913
Revises: bb3329253f22
Create Date: 2026-09-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5e8d2a7f913"
down_revision: str | Sequence[str] | None = "bb3329253f22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable planned_ev_charging_kwh; existing rows stay NULL (unknown)."""
    with op.batch_alter_table("slot_plans") as batch_op:
        batch_op.add_column(sa.Column("planned_ev_charging_kwh", sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove planned_ev_charging_kwh from slot_plans."""
    with op.batch_alter_table("slot_plans") as batch_op:
        batch_op.drop_column("planned_ev_charging_kwh")
