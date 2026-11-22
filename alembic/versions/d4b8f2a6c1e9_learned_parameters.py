"""learned parameters tables; drop dead reflex_state and learning_daily_metrics

Creates ``learned_parameters``, ``learned_parameter_history`` and
``inverter_loss_observations`` (learned-battery-inverter-parameters) and drops
the Reflex-only tables ``reflex_state`` and ``learning_daily_metrics``, which
nothing reads any more.

Revision ID: d4b8f2a6c1e9
Revises: c3a9e5d7b1f2
Create Date: 2026-11-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4b8f2a6c1e9"
down_revision: str | Sequence[str] | None = "c3a9e5d7b1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("learned_parameters", "learned_parameter_history", "inverter_loss_observations")
HISTORY_INDEX = "ix_learned_parameter_history_key_at"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _has_history_index() -> bool:
    indexes = sa.inspect(op.get_bind()).get_indexes("learned_parameter_history")
    return any(index["name"] == HISTORY_INDEX for index in indexes)


def upgrade() -> None:
    """Upgrade schema."""
    existing = _tables()
    if "learned_parameters" not in existing:
        op.create_table(
            "learned_parameters",
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("learned_value", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_json", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
            sa.Column("estimated_at", sa.String(), nullable=True),
            sa.Column("applied_value", sa.Float(), nullable=True),
            sa.Column("applied_at", sa.String(), nullable=True),
            sa.Column("status_note", sa.Text(), nullable=True),
            sa.Column("locked", sa.Integer(), server_default=sa.text("0"), nullable=False),
            sa.Column("locked_value", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )
    if "learned_parameter_history" not in existing:
        op.create_table(
            "learned_parameter_history",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("at", sa.String(), nullable=False),
            sa.Column("event", sa.String(), nullable=False),
            sa.Column("old_value", sa.Float(), nullable=True),
            sa.Column("new_value", sa.Float(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_json", sa.Text(), nullable=True),
            sa.Column(
                "notify_state", sa.String(), server_default=sa.text("'none'"), nullable=False
            ),
            sa.Column("notified_at", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    if "learned_parameter_history" not in existing or not _has_history_index():
        op.create_index(HISTORY_INDEX, "learned_parameter_history", ["key", "at"], unique=False)
    if "inverter_loss_observations" not in existing:
        op.create_table(
            "inverter_loss_observations",
            sa.Column("slot_start", sa.String(), nullable=False),
            sa.Column("loss_kwh", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("slot_start"),
        )
    for dead in ("reflex_state", "learning_daily_metrics"):
        if dead in existing:
            op.drop_table(dead)


def downgrade() -> None:
    """Downgrade schema (the two dropped tables come back empty)."""
    existing = _tables()
    if "learned_parameter_history" in existing and _has_history_index():
        op.drop_index(HISTORY_INDEX, table_name="learned_parameter_history")
    for name in NEW_TABLES:
        if name in existing:
            op.drop_table(name)
    if "learning_daily_metrics" not in existing:
        op.create_table(
            "learning_daily_metrics",
            sa.Column("date", sa.String(), nullable=False),
            sa.Column("pv_error_by_hour_kwh", sa.Text(), nullable=True),
            sa.Column("load_error_by_hour_kwh", sa.Text(), nullable=True),
            sa.Column("pv_adjustment_by_hour_kwh", sa.Text(), nullable=True),
            sa.Column("load_adjustment_by_hour_kwh", sa.Text(), nullable=True),
            sa.Column("soc_error_mean_pct", sa.Float(), nullable=True),
            sa.Column("soc_error_stddev_pct", sa.Float(), nullable=True),
            sa.Column("pv_error_mean_abs_kwh", sa.Float(), nullable=True),
            sa.Column("load_error_mean_abs_kwh", sa.Float(), nullable=True),
            sa.Column("s_index_base_factor", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("date"),
        )
    if "reflex_state" not in existing:
        op.create_table(
            "reflex_state",
            sa.Column("param_path", sa.String(), nullable=False),
            sa.Column("last_value", sa.Float(), nullable=True),
            sa.Column("last_updated", sa.String(), nullable=True),
            sa.Column("change_count", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("param_path"),
        )
