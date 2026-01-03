from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from learning import LearningEngine, get_learning_engine

from ml.policy.antares_policy import AntaresPolicyV1
from ml.policy.antares_rl_policy import AntaresRLPolicyV1


@dataclass
class PolicyRunInfo:
    run_id: str
    models_dir: str
    kind: str  # 'supervised' or 'rl'


def _load_latest_supervised_run(engine: LearningEngine) -> PolicyRunInfo | None:
    """Load the most recent supervised (LightGBM) policy run metadata from SQLite."""
    import sqlite3

    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, models_dir
                FROM antares_policy_runs
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None

    if row is None:
        return None
    return PolicyRunInfo(run_id=str(row[0]), models_dir=str(row[1]), kind="supervised")


def _load_latest_rl_run(engine: LearningEngine) -> PolicyRunInfo | None:
    """Load the most recent RL policy run metadata from SQLite."""
    import sqlite3

    try:
        with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
            row = conn.execute(
                """
                SELECT run_id, artifact_dir
                FROM antares_rl_runs
                ORDER BY created_at DESC
                LIMIT 1
                """
            ).fetchone()
    except sqlite3.Error:
        row = None

    if row is None:
        return None
    return PolicyRunInfo(run_id=str(row[0]), models_dir=str(row[1]), kind="rl")


def _build_state_from_row(row: pd.Series, *, hour_of_day: int) -> np.ndarray:
    """Build policy state vector from a schedule row."""
    load_forecast = float(row.get("load_forecast_kwh", 0.0) or 0.0)
    pv_forecast = float(row.get("pv_forecast_kwh", 0.0) or 0.0)
    projected_soc = float(row.get("projected_soc_percent", 0.0) or 0.0)
    import_price = float(row.get("import_price_sek_kwh", 0.0) or 0.0)
    export_price = float(row.get("export_price_sek_kwh", import_price) or import_price)

    state = np.array(
        [
            float(hour_of_day),
            load_forecast,
            pv_forecast,
            projected_soc,
            import_price,
            export_price,
        ],
        dtype=np.float32,
    )
    return state


def _apply_action_clamps(
    action: dict[str, float],
    *,
    max_charge_kw: float,
    max_discharge_kw: float,
    max_export_kw: float,
) -> dict[str, float]:
    """Clamp raw policy outputs to simple physical limits."""
    charge = float(action.get("battery_charge_kw", 0.0) or 0.0)
    discharge = float(action.get("battery_discharge_kw", 0.0) or 0.0)
    export_kw = float(action.get("export_kw", 0.0) or 0.0)

    charge = max(0.0, min(charge, max_charge_kw))
    discharge = max(0.0, min(discharge, max_discharge_kw))
    export_kw = max(0.0, min(export_kw, max_export_kw))

    # Simple mutual exclusivity: prefer discharge when both requested.
    if charge > 0.0 and discharge > 0.0:
        if discharge >= charge:
            charge = 0.0
        else:
            discharge = 0.0

    return {
        "battery_charge_kw": charge,
        "battery_discharge_kw": discharge,
        "export_kw": export_kw,
    }


def _build_shadow_schedule_df(
    schedule_df: pd.DataFrame,
    policy: Any,
    engine: LearningEngine,
) -> pd.DataFrame:
    """Return a copy of the schedule with Antares actions applied."""
    cfg = engine.config
    system_cfg = cfg.get("system", {}) or {}
    battery_cfg = system_cfg.get("battery", {}) or cfg.get("battery", {}) or {}
    grid_cfg = system_cfg.get("grid", {}) or {}
    inverter_cfg = system_cfg.get("inverter", {}) or {}

    max_charge_kw = float(battery_cfg.get("max_charge_power_kw", 3.0))
    max_discharge_kw = float(battery_cfg.get("max_discharge_power_kw", 3.0))
    inverter_limit = float(inverter_cfg.get("max_power_kw", 10.0))
    grid_limit = float(grid_cfg.get("max_power_kw", inverter_limit))
    max_export_kw = min(inverter_limit, grid_limit)

    tz = engine.timezone

    df = schedule_df.copy(deep=True)
    if "start_time" not in df.columns:
        raise ValueError("schedule_df must contain a 'start_time' column")

    starts = pd.to_datetime(df["start_time"])
    starts = starts.dt.tz_localize(tz) if starts.dt.tz is None else starts.dt.tz_convert(tz)

    df["start_time"] = starts.dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    new_charge: list[float] = []
    new_discharge: list[float] = []
    new_export_kwh: list[float] = []

    for idx, row in df.iterrows():
        start_ts = starts.iloc[idx]
        hour = int(start_ts.hour)
        state = _build_state_from_row(row, hour_of_day=hour)
        raw_action = policy.predict(state)
        clamped = _apply_action_clamps(
            raw_action,
            max_charge_kw=max_charge_kw,
            max_discharge_kw=max_discharge_kw,
            max_export_kw=max_export_kw,
        )

        charge_kw = clamped["battery_charge_kw"]
        discharge_kw = clamped["battery_discharge_kw"]
        export_kw = clamped["export_kw"]
        export_kwh = export_kw * 0.25

        new_charge.append(charge_kw)
        new_discharge.append(discharge_kw)
        new_export_kwh.append(export_kwh)

    df["battery_charge_kw"] = new_charge
    df["battery_discharge_kw"] = new_discharge
    df["export_kwh"] = new_export_kwh

    return df


def run_shadow_for_schedule(
    schedule_df: pd.DataFrame,
    *,
    policy_type: str = "lightgbm",
    system_suffix: str | None = None,
) -> dict[str, Any] | None:
    """
    Build an Antares shadow schedule payload for the given planner schedule.

    Returns:
        Dict with keys:
            - system_id
            - plan_date
            - episode_start_local
            - policy_run_id
            - schedule (list of slot dicts)
            - metrics (summary dict)
        Or None if no policy is available.
    """
    engine = get_learning_engine()
    if policy_type == "rl":
        antares_cfg = engine.config.get("antares", {}) or {}
        if not bool(antares_cfg.get("enable_rl_shadow_mode", False)):
            print(
                "[shadow] RL shadow mode requested but antares.enable_rl_shadow_mode "
                "is false; skipping RL shadow plan."
            )
            return None
        run = _load_latest_rl_run(engine)
        if run is None:
            print("[shadow] No entries in antares_rl_runs; skipping RL shadow plan.")
            return None
        policy = AntaresRLPolicyV1.load_from_dir(run.models_dir)
        effective_suffix = system_suffix or "shadow_rl_v1"
    else:
        run = _load_latest_supervised_run(engine)
        if run is None:
            print("[shadow] No entries in antares_policy_runs; skipping shadow plan.")
            return None
        policy = AntaresPolicyV1.load_from_dir(run.models_dir)
        effective_suffix = system_suffix or "shadow_v1"

    shadow_df = _build_shadow_schedule_df(schedule_df, policy, engine)
    if shadow_df.empty:
        print("[shadow] Empty schedule; nothing to store.")
        return None

    tz = engine.timezone
    first_start_raw = shadow_df.iloc[0]["start_time"]
    first_ts = pd.to_datetime(first_start_raw)
    first_ts = tz.localize(first_ts) if first_ts.tzinfo is None else first_ts.astimezone(tz)

    plan_date = first_ts.date().isoformat()
    episode_start_local = first_ts.replace(microsecond=0).isoformat()

    base_system_id = str(engine.config.get("system", {}).get("system_id", "prod"))
    system_id = f"{base_system_id}_{effective_suffix}"

    schedule_records = shadow_df.to_dict(orient="records")
    metrics = {
        "slots": len(schedule_records),
    }

    payload: dict[str, Any] = {
        "system_id": system_id,
        "plan_date": plan_date,
        "episode_start_local": episode_start_local,
        "policy_run_id": run.run_id,
        "schedule": schedule_records,
        "metrics": metrics,
    }
    return payload
