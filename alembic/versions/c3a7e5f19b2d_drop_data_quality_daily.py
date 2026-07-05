"""drop data_quality_daily

Dead since the backfill era (no live writer/reader); the stabilization-review-2
runtime invariant monitors are its live-era replacement. Downgrade recreates
an empty table only — historical rows are not restored.

Revision ID: c3a7e5f19b2d
Revises: 8f2c4d6e9a10
Create Date: 2026-07-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a7e5f19b2d"
down_revision: str | Sequence[str] | None = "8f2c4d6e9a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "data_quality_daily" in inspector.get_table_names():
        op.drop_table("data_quality_daily")


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "data_quality_daily" not in inspector.get_table_names():
        op.create_table(
            "data_quality_daily",
            sa.Column("date", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("bad_hours_load", sa.Integer(), nullable=False),
            sa.Column("bad_hours_pv", sa.Integer(), nullable=False),
            sa.Column("bad_hours_import", sa.Integer(), nullable=False),
            sa.Column("bad_hours_export", sa.Integer(), nullable=False),
            sa.Column("bad_hours_batt", sa.Integer(), nullable=False),
            sa.Column("missing_slots", sa.Integer(), nullable=False),
            sa.Column("soc_issues", sa.Integer(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("date"),
        )
