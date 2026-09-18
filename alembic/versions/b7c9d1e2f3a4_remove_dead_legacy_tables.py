"""remove dead legacy learning tables

Revision ID: b7c9d1e2f3a4
Revises: 3fa1a48708be
Create Date: 2026-09-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c9d1e2f3a4"
down_revision: str | Sequence[str] | None = "3fa1a48708be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEAD_TABLES = (
    "battery_cost",
    "antares_rl_runs",
    "antares_training_runs",
    "antares_policy_runs",
    "training_episodes",
    "strategy_log",
    "daily_water",
    "sensor_totals",
    "realized_energy",
)


def upgrade() -> None:
    """Drop dead tables that are present in this database."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in DEAD_TABLES:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    """Recreate the removed tables empty for rollback parity."""
    op.create_table(
        "battery_cost",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("avg_cost_sek_per_kwh", sa.Float(), nullable=False),
        sa.Column("energy_kwh", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "antares_rl_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("algo", sa.String(), nullable=False),
        sa.Column("state_version", sa.String(), nullable=False),
        sa.Column("action_version", sa.String(), nullable=False),
        sa.Column("train_start_date", sa.String(), nullable=True),
        sa.Column("train_end_date", sa.String(), nullable=True),
        sa.Column("val_start_date", sa.String(), nullable=True),
        sa.Column("val_end_date", sa.String(), nullable=True),
        sa.Column("hyperparams_json", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=True),
        sa.Column("artifact_dir", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "antares_training_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("dataset_version", sa.String(), nullable=False),
        sa.Column("train_start_date", sa.String(), nullable=False),
        sa.Column("train_end_date", sa.String(), nullable=False),
        sa.Column("val_start_date", sa.String(), nullable=True),
        sa.Column("val_end_date", sa.String(), nullable=True),
        sa.Column("targets", sa.String(), nullable=False),
        sa.Column("model_type", sa.String(), nullable=False),
        sa.Column("hyperparams_json", sa.Text(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("artifact_dir", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "antares_policy_runs",
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("models_dir", sa.String(), nullable=False),
        sa.Column("target_names", sa.String(), nullable=False),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_table(
        "training_episodes",
        sa.Column("episode_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("inputs_json", sa.Text(), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=True),
        sa.Column("schedule_json", sa.Text(), nullable=False),
        sa.Column("config_overrides_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("episode_id"),
    )
    op.create_table(
        "strategy_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("timestamp", sa.String(), nullable=False),
        sa.Column("overrides_json", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "daily_water",
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("used_kwh", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("date"),
    )
    op.create_table(
        "sensor_totals",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("last_value", sa.Float(), nullable=True),
        sa.Column("last_timestamp", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "realized_energy",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slot_start", sa.String(), nullable=False),
        sa.Column("slot_end", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=True),
        sa.Column("energy_kwh", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
