from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SlotObservation(Base):
    __tablename__ = "slot_observations"

    slot_start: Mapped[str] = mapped_column(String, primary_key=True)
    slot_end: Mapped[str] = mapped_column(String)
    import_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    export_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    pv_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    load_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    water_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    batt_charge_kwh: Mapped[float | None] = mapped_column(Float)
    batt_discharge_kwh: Mapped[float | None] = mapped_column(Float)
    soc_start_percent: Mapped[float | None] = mapped_column(Float)
    soc_end_percent: Mapped[float | None] = mapped_column(Float)
    import_price_sek_kwh: Mapped[float | None] = mapped_column(Float)
    export_price_sek_kwh: Mapped[float | None] = mapped_column(Float)
    executed_action: Mapped[str | None] = mapped_column(String)
    quality_flags: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class SlotForecast(Base):
    __tablename__ = "slot_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_start: Mapped[str] = mapped_column(String)
    pv_forecast_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    load_forecast_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    pv_p10: Mapped[float | None] = mapped_column(Float)
    pv_p90: Mapped[float | None] = mapped_column(Float)
    load_p10: Mapped[float | None] = mapped_column(Float)
    load_p90: Mapped[float | None] = mapped_column(Float)
    temp_c: Mapped[float | None] = mapped_column(Float)
    forecast_version: Mapped[str] = mapped_column(String)
    pv_correction_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    load_correction_kwh: Mapped[float] = mapped_column(Float, default=0.0, server_default=text("0"))
    correction_source: Mapped[str] = mapped_column(String, default="none", server_default=text("'none'"))
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    __table_args__ = (UniqueConstraint("slot_start", "forecast_version"),)


class SlotPlan(Base):
    __tablename__ = "slot_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_start: Mapped[str] = mapped_column(String, unique=True)
    planned_charge_kwh: Mapped[float | None] = mapped_column(Float)
    planned_discharge_kwh: Mapped[float | None] = mapped_column(Float)
    planned_soc_percent: Mapped[float | None] = mapped_column(Float)
    planned_import_kwh: Mapped[float | None] = mapped_column(Float)
    planned_export_kwh: Mapped[float | None] = mapped_column(Float)
    planned_water_heating_kwh: Mapped[float | None] = mapped_column(Float)
    planned_cost_sek: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class ConfigVersion(Base):
    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    yaml_blob: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)


class LearningRun(Base):
    __tablename__ = "learning_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    horizon_days: Mapped[int] = mapped_column(Integer, default=7)
    params_json: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="started")
    result_metrics_json: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)


class LearningDailyMetric(Base):
    __tablename__ = "learning_daily_metrics"

    date: Mapped[str] = mapped_column(String, primary_key=True)
    pv_error_by_hour_kwh: Mapped[str | None] = mapped_column(Text)
    load_error_by_hour_kwh: Mapped[str | None] = mapped_column(Text)
    pv_adjustment_by_hour_kwh: Mapped[str | None] = mapped_column(Text)
    load_adjustment_by_hour_kwh: Mapped[str | None] = mapped_column(Text)
    soc_error_mean_pct: Mapped[float | None] = mapped_column(Float)
    soc_error_stddev_pct: Mapped[float | None] = mapped_column(Float)
    pv_error_mean_abs_kwh: Mapped[float | None] = mapped_column(Float)
    load_error_mean_abs_kwh: Mapped[float | None] = mapped_column(Float)
    s_index_base_factor: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class LearningParamHistory(Base):
    __tablename__ = "learning_param_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(Integer)
    param_path: Mapped[str] = mapped_column(String)
    old_value: Mapped[str | None] = mapped_column(String)
    new_value: Mapped[str | None] = mapped_column(String)
    loop: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )


class SensorTotal(Base):
    __tablename__ = "sensor_totals"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    last_value: Mapped[float | None] = mapped_column(Float)
    last_timestamp: Mapped[str | None] = mapped_column(String)


class TrainingEpisode(Base):
    __tablename__ = "training_episodes"

    episode_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, default=datetime.utcnow
    )
    inputs_json: Mapped[str] = mapped_column(Text)
    context_json: Mapped[str | None] = mapped_column(Text)
    schedule_json: Mapped[str] = mapped_column(Text)
    config_overrides_json: Mapped[str | None] = mapped_column(Text)


class SchedulePlanned(Base):
    __tablename__ = "schedule_planned"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String, index=True)
    planned_kwh: Mapped[float] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String)


class RealizedEnergy(Base):
    __tablename__ = "realized_energy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_start: Mapped[str] = mapped_column(String)
    slot_end: Mapped[str] = mapped_column(String)
    action: Mapped[str | None] = mapped_column(String)
    energy_kwh: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[str] = mapped_column(String)


class DailyWater(Base):
    __tablename__ = "daily_water"

    date: Mapped[str] = mapped_column(String, primary_key=True)
    used_kwh: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[str] = mapped_column(String)


class PlannerDebug(Base):
    __tablename__ = "planner_debug"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String)
    payload: Mapped[str] = mapped_column(Text)


class StrategyLog(Base):
    __tablename__ = "strategy_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String)
    timestamp: Mapped[str] = mapped_column(String)
    overrides_json: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(String)


class ReflexState(Base):
    __tablename__ = "reflex_state"

    param_path: Mapped[str] = mapped_column(String, primary_key=True)
    last_value: Mapped[float | None] = mapped_column(Float)
    last_updated: Mapped[str | None] = mapped_column(String)
    change_count: Mapped[int] = mapped_column(Integer, default=0)


class AntaresRLRun(Base):
    __tablename__ = "antares_rl_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
    algo: Mapped[str] = mapped_column(String)
    state_version: Mapped[str] = mapped_column(String)
    action_version: Mapped[str] = mapped_column(String)
    train_start_date: Mapped[str | None] = mapped_column(String)
    train_end_date: Mapped[str | None] = mapped_column(String)
    val_start_date: Mapped[str | None] = mapped_column(String)
    val_end_date: Mapped[str | None] = mapped_column(String)
    hyperparams_json: Mapped[str | None] = mapped_column(Text)
    metrics_json: Mapped[str | None] = mapped_column(Text)
    artifact_dir: Mapped[str] = mapped_column(String)


class AntaresTrainingRun(Base):
    __tablename__ = "antares_training_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
    dataset_version: Mapped[str] = mapped_column(String)
    train_start_date: Mapped[str] = mapped_column(String)
    train_end_date: Mapped[str] = mapped_column(String)
    val_start_date: Mapped[str | None] = mapped_column(String)
    val_end_date: Mapped[str | None] = mapped_column(String)
    targets: Mapped[str] = mapped_column(String)
    model_type: Mapped[str] = mapped_column(String)
    hyperparams_json: Mapped[str] = mapped_column(Text)
    metrics_json: Mapped[str] = mapped_column(Text)
    artifact_dir: Mapped[str] = mapped_column(String)


class AntaresPolicyRun(Base):
    __tablename__ = "antares_policy_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[str] = mapped_column(String)
    models_dir: Mapped[str] = mapped_column(String)
    target_names: Mapped[str] = mapped_column(String)
    metrics_json: Mapped[str] = mapped_column(Text)


class BatteryCost(Base):
    __tablename__ = "battery_cost"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    avg_cost_sek_per_kwh: Mapped[float] = mapped_column(Float)
    energy_kwh: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[str] = mapped_column(String)


class VacationState(Base):
    __tablename__ = "vacation_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[str | None] = mapped_column(String)


class DataQualityDaily(Base):
    __tablename__ = "data_quality_daily"

    date: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String)
    bad_hours_load: Mapped[int] = mapped_column(Integer, default=0)
    bad_hours_pv: Mapped[int] = mapped_column(Integer, default=0)
    bad_hours_import: Mapped[int] = mapped_column(Integer, default=0)
    bad_hours_export: Mapped[int] = mapped_column(Integer, default=0)
    bad_hours_batt: Mapped[int] = mapped_column(Integer, default=0)
    missing_slots: Mapped[int] = mapped_column(Integer, default=0)
    soc_issues: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str | None] = mapped_column(Text)


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    executed_at: Mapped[str] = mapped_column(String, index=True)
    slot_start: Mapped[str] = mapped_column(String, index=True)
    planned_charge_kw: Mapped[float | None] = mapped_column(Float)
    planned_discharge_kw: Mapped[float | None] = mapped_column(Float)
    planned_export_kw: Mapped[float | None] = mapped_column(Float)
    planned_water_kw: Mapped[float | None] = mapped_column(Float)
    planned_soc_target: Mapped[int | None] = mapped_column(Integer)
    planned_soc_projected: Mapped[int | None] = mapped_column(Integer)
    commanded_work_mode: Mapped[str | None] = mapped_column(String)
    commanded_grid_charging: Mapped[int | None] = mapped_column(Integer)
    commanded_charge_current_a: Mapped[float | None] = mapped_column(Float)
    commanded_discharge_current_a: Mapped[float | None] = mapped_column(Float)
    commanded_soc_target: Mapped[int | None] = mapped_column(Integer)
    commanded_water_temp: Mapped[int | None] = mapped_column(Integer)
    before_soc_percent: Mapped[float | None] = mapped_column(Float)
    before_work_mode: Mapped[str | None] = mapped_column(String)
    before_water_temp: Mapped[float | None] = mapped_column(Float)
    before_pv_kw: Mapped[float | None] = mapped_column(Float)
    before_load_kw: Mapped[float | None] = mapped_column(Float)
    override_active: Mapped[int] = mapped_column(Integer, default=0)
    override_type: Mapped[str | None] = mapped_column(String)
    override_reason: Mapped[str | None] = mapped_column(String)
    success: Mapped[int] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String, default="native")
    executor_version: Mapped[str | None] = mapped_column(String)
    commanded_unit: Mapped[str] = mapped_column(String, default="A")
