from __future__ import annotations

"""
Inspect Antares RL behaviour for a single day.

Usage:
    PYTHONPATH=. python debug/run_rl_policy_for_day.py --day 2025-11-20
"""

import argparse
import sqlite3
from typing import Any

import pandas as pd
from learning import LearningEngine, get_learning_engine

from ml.policy.antares_rl_policy import AntaresRLPolicyV1
from ml.simulation.env import AntaresMPCEnv


def _load_latest_rl_run(engine: LearningEngine) -> dict[str, str]:
    with sqlite3.connect(engine.db_path, timeout=30.0) as conn:
        row = conn.execute(
            """
            SELECT run_id, artifact_dir
            FROM antares_rl_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise SystemExit("[rl-day] No antares_rl_runs rows; train RL first.")
    return {"run_id": row[0], "artifact_dir": row[1]}


def _compute_slot_cost(row: pd.Series, cycle_cost_kwh: float) -> float:
    start_ts = pd.Timestamp(row.get("start_time"))
    end_ts = pd.Timestamp(row.get("end_time"))
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("Europe/Stockholm")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("Europe/Stockholm")
    slot_hours = max(0.25, (end_ts - start_ts).total_seconds() / 3600.0)

    charge_kw = max(0.0, float(row.get("battery_charge_kw", row.get("charge_kw", 0.0) or 0.0)))
    discharge_kw = max(0.0, float(row.get("battery_discharge_kw", 0.0)))
    charge_kwh = charge_kw * slot_hours
    discharge_kwh = discharge_kw * slot_hours

    adjusted_load = float(row.get("adjusted_load_kwh", 0.0))
    adjusted_pv = float(row.get("adjusted_pv_kwh", 0.0))
    water_grid = float(row.get("water_from_grid_kwh", 0.0))
    water_pv = float(row.get("water_from_pv_kwh", 0.0))

    export_kwh = float(row.get("export_kwh", 0.0))

    grid_import_kwh = max(
        0.0,
        adjusted_load + water_grid + charge_kwh - adjusted_pv - discharge_kwh - water_pv,
    )

    import_price = float(row.get("import_price_sek_kwh", 0.0))
    export_price = float(row.get("export_price_sek_kwh", import_price))

    cost = grid_import_kwh * import_price
    revenue = export_kwh * export_price
    wear = (charge_kwh + discharge_kwh) * cycle_cost_kwh

    return float(cost - revenue + wear)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Antares RL behaviour for a single day.")
    parser.add_argument("--day", required=True, help="Day to evaluate (YYYY-MM-DD)")
    args = parser.parse_args()

    tz = "Europe/Stockholm"

    engine = get_learning_engine()
    rl_run = _load_latest_rl_run(engine)

    print("[rl-day] Using RL run:")
    print(f"  run_id:      {rl_run['run_id']}")
    print(f"  artifact_dir:{rl_run['artifact_dir']}")

    policy = AntaresRLPolicyV1.load_from_dir(rl_run["artifact_dir"])

    # Build base schedule and env.
    env = AntaresMPCEnv(config_path="config.yaml")
    state = env.reset(args.day)

    # Reconstruct the MPC schedule DataFrame used internally.
    schedule = env._schedule.copy()  # type: ignore[attr-defined]
    if schedule.index.name in {"start_time", "slot_start"} and "start_time" not in schedule.columns:
        schedule = schedule.reset_index()

    cycle_cost = engine.config.get("battery_economics", {}).get("battery_cycle_cost_kwh", 0.20)

    records: list[dict[str, Any]] = []

    for idx in range(len(schedule)):
        row = schedule.iloc[idx].copy()
        start_time = row.get("start_time")
        end_time = row.get("end_time")

        start_ts = pd.Timestamp(start_time)
        end_ts = pd.Timestamp(end_time)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(tz)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize(tz)
        slot_hours = max(0.25, (end_ts - start_ts).total_seconds() / 3600.0)

        import_price = float(row.get("import_price_sek_kwh", 0.0))
        export_price = float(row.get("export_price_sek_kwh", import_price))

        # MPC actions from schedule
        mpc_charge = float(row.get("battery_charge_kw", row.get("charge_kw", 0.0) or 0.0))
        mpc_discharge = float(row.get("battery_discharge_kw", 0.0))
        mpc_export_kwh = float(row.get("export_kwh", 0.0))

        # RL action
        # State vector fed to the policy; index 3 is projected SoC percent.
        state_soc_percent = float(state[3]) if len(state) > 3 else float("nan")
        action = policy.predict(state)
        result = env.step(action=action)

        # Raw RL proposal (before environment clamping)
        rl_charge_raw = float(action.get("battery_charge_kw", 0.0) or 0.0)
        rl_discharge_raw = float(action.get("battery_discharge_kw", 0.0) or 0.0)

        # Effective actions used by the environment (after clamping and SoC limits)
        eff_charge = float(result.info.get("battery_charge_kw", rl_charge_raw))
        eff_discharge = float(result.info.get("battery_discharge_kw", rl_discharge_raw))
        eff_net = float(result.info.get("net_battery_kw", eff_charge - eff_discharge))
        eff_export_kwh = float(result.info.get("export_kwh", row.get("export_kwh", 0.0) or 0.0))

        # Internal SoC as used by the environment and schedule-projected SoC.
        soc_kwh_internal = float(result.info.get("soc_kwh", 0.0))
        soc_percent_internal = float(result.info.get("soc_percent_internal", 0.0))
        projected_soc_percent = float(result.info.get("projected_soc_percent", 0.0))

        # Numerically integrate SoC from flows for a cross-check.
        soc_kwh_num = soc_kwh_internal - (eff_charge - eff_discharge) * slot_hours

        # Build an effective row for RL cost calculation.
        rl_row = row.copy()
        rl_row["battery_charge_kw"] = eff_charge
        rl_row["battery_discharge_kw"] = eff_discharge
        rl_row["export_kwh"] = eff_export_kwh

        slot_cost = _compute_slot_cost(rl_row, cycle_cost_kwh=cycle_cost)

        records.append(
            {
                "slot_index": idx,
                "start_time": start_time,
                "end_time": end_time,
                "slot_hours": slot_hours,
                "import_price": import_price,
                "export_price": export_price,
                "mpc_charge_kw": mpc_charge,
                "mpc_discharge_kw": mpc_discharge,
                "mpc_export_kwh": mpc_export_kwh,
                "rl_charge_kw_raw": rl_charge_raw,
                "rl_discharge_kw_raw": rl_discharge_raw,
                "rl_charge_kw_eff": eff_charge,
                "rl_discharge_kw_eff": eff_discharge,
                # Convention: positive = charging, negative = discharging.
                "rl_net_battery_kw_eff": eff_net,
                "rl_export_kwh_eff": eff_export_kwh,
                "soc_kwh_internal": soc_kwh_internal,
                "soc_percent_internal": soc_percent_internal,
                "soc_percent_projected": projected_soc_percent,
                "soc_percent_from_state": state_soc_percent,
                "soc_kwh_numeric_from_flows": soc_kwh_num,
                "slot_cost_sek": slot_cost,
                "reward": float(result.reward),
            }
        )

        state = result.next_state
        if result.done:
            break

    df = pd.DataFrame(records)
    if df.empty:
        print("[rl-day] No records produced.")
        return 1

    print("\n[rl-day] First 5 slots:")
    print(df.head(5).to_string(index=False))

    print("\n[rl-day] Last 5 slots:")
    print(df.tail(5).to_string(index=False))

    total_cost = float(df["slot_cost_sek"].sum())
    print(f"\n[rl-day] Total RL cost for {args.day}: {total_cost:.2f} SEK")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
