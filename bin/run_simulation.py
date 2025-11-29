"""CLI for replaying historical data through the planner."""

import argparse
import copy
import learning
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

import pandas as pd
import pytz
import yaml

from ml.simulation.data_loader import SimulationDataLoader
from planner import HeliosPlanner


def _parse_date(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Dates must be ISO formatted (YYYY-MM-DD or YYYY-MM-DDTHH:MM).")


def _build_sim_config(base_config: dict) -> dict:
    sim_config = copy.deepcopy(base_config)
    system_cfg = sim_config.setdefault("system", {})
    system_cfg["system_id"] = "simulation"
    return sim_config


def _write_temp_config(sim_config: dict) -> str:
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".yaml", mode="w", encoding="utf-8")
    yaml.safe_dump(sim_config, handle)
    handle.flush()
    handle.close()
    return handle.name


def _localize_datetime(value: datetime, timezone_name: str) -> datetime:
    tz = pytz.timezone(timezone_name)
    if value.tzinfo is None:
        return tz.localize(value)
    return value.astimezone(tz)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run historical planner simulations.")
    parser.add_argument("--start-date", required=True, type=_parse_date)
    parser.add_argument("--end-date", required=True, type=_parse_date)
    parser.add_argument("--step-minutes", type=int, default=15, help="Simulation increment in minutes.")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        with open("config.yaml", "r", encoding="utf-8") as fp:
            base_config = yaml.safe_load(fp) or {}
    except FileNotFoundError:
        print("config.yaml not found. Please run from project root.")
        return 1

    timezone_name = base_config.get("timezone", "Europe/Stockholm")
    start_time = _localize_datetime(args.start_date, timezone_name)
    end_time = _localize_datetime(args.end_date, timezone_name)

    if end_time <= start_time:
        print("Error: end-date must be later than start-date.")
        return 1

    sim_config = _build_sim_config(base_config)
    temp_config_path = _write_temp_config(sim_config)
    previous_engine = None

    try:
        sim_engine = learning.LearningEngine(temp_config_path)
        previous_engine = getattr(learning, "_learning_engine", None)
        learning._learning_engine = sim_engine
        planner = HeliosPlanner(temp_config_path)
        loader = SimulationDataLoader(temp_config_path)

        # Load per-day data quality classifications, if available, so that
        # only clean/mask_battery days produce simulation episodes.
        quality_by_date = {}
        try:
            with sqlite3.connect(loader.db_path, timeout=30.0) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT date, status FROM data_quality_daily"
                )
                quality_by_date = {
                    row[0]: row[1] for row in cur.fetchall() if row and row[0]
                }
        except sqlite3.Error:
            quality_by_date = {}

        # Discover available historical window for user feedback
        first_slot = None
        last_slot = None
        try:
            with sqlite3.connect(loader.db_path, timeout=30.0) as conn:
                cur = conn.cursor()
                cur.execute("SELECT MIN(slot_start), MAX(slot_start) FROM slot_observations")
                first_slot, last_slot = cur.fetchone()
        except sqlite3.Error:
            pass

        initial_state = loader.get_initial_state_from_history(start_time)

        current = start_time
        step = timedelta(minutes=args.step_minutes)

        while current < end_time:
            input_data = loader.get_window_inputs(current)
            price_slots = input_data.get("price_data") or []
            if not price_slots:
                window_end = current + timedelta(hours=loader.horizon_hours)
                print(
                    "[simulation] No price data in slot_observations for "
                    f"window {current.isoformat()} → {window_end.isoformat()}."
                )
                if first_slot and last_slot:
                    print(
                        "[simulation] Available observation range is "
                        f"{first_slot} → {last_slot}."
                    )
                else:
                    print(
                        "[simulation] slot_observations is empty or unreachable; "
                        "run the planner / data_activator to populate it."
                    )
                break

            input_data["initial_state"] = {
                "battery_soc_percent": initial_state["battery_soc_percent"],
                "battery_kwh": initial_state["battery_kwh"],
                "battery_cost_sek_per_kwh": initial_state["battery_cost_sek_per_kwh"],
            }

            # Surface the simulation clock for downstream consumers (learning, JSON).
            input_data["now_override"] = current

            # Enrich context so logged episodes can be aligned back to
            # slot_observations and data_quality_daily.
            context = dict(input_data.get("context") or {})
            current_day = current.date().isoformat()
            quality_status = quality_by_date.get(current_day, "unknown")
            context.update(
                {
                    "episode_start_local": current.isoformat(),
                    "episode_date": current_day,
                    "system_id": sim_config.get("system", {}).get(
                        "system_id", "simulation"
                    ),
                    "data_quality_status": quality_status,
                }
            )
            input_data["context"] = context

            # Only log training episodes for days that pass data-quality filters.
            record_episode = quality_status in {"clean", "mask_battery"} or not quality_by_date

            schedule = planner.generate_schedule(
                input_data,
                record_training_episode=record_episode,
                now_override=current,
                save_to_file=False,
            )

            if schedule.empty:
                print(f"[simulation] Empty schedule at {current.isoformat()}, stopping.")
                break

            # Find the row corresponding to the current simulation step
            try:
                target_idx = current
                if getattr(schedule.index, "tz", None) is None:
                    target_idx = current.replace(tzinfo=None)

                step_row = schedule.loc[target_idx]
                if isinstance(step_row, pd.DataFrame):
                    # In the unlikely event of duplicate indices, use the first match.
                    step_row = step_row.iloc[0]

                projected_soc = step_row["projected_soc_percent"]
                projected_kwh = step_row["projected_soc_kwh"]
                projected_cost = step_row["projected_battery_cost"]

                if projected_soc is None or projected_kwh is None:
                    print(
                        f"[simulation] Invalid SOC data at {current.isoformat()}, stopping."
                    )
                    break

                try:
                    soc_float = float(projected_soc)
                    kwh_float = float(projected_kwh)
                except (TypeError, ValueError):
                    print(
                        f"[simulation] Cannot parse SOC at {current.isoformat()}, stopping."
                    )
                    break

                if math.isnan(soc_float) or math.isnan(kwh_float):
                    print(
                        f"[simulation] SOC contains NaN at {current.isoformat()}, stopping."
                    )
                    break

                if projected_cost is None or (
                    isinstance(projected_cost, float) and math.isnan(projected_cost)
                ):
                    cost_float = initial_state["battery_cost_sek_per_kwh"]
                else:
                    try:
                        cost_float = float(projected_cost)
                    except (TypeError, ValueError):
                        cost_float = initial_state["battery_cost_sek_per_kwh"]

                initial_state = {
                    "battery_soc_percent": soc_float,
                    "battery_kwh": kwh_float,
                    "battery_cost_sek_per_kwh": cost_float,
                }
            except KeyError:
                print(
                    f"[simulation] Warning: Could not find row for {current} in schedule. "
                    "Using previous state."
                )

            # --- DEBUG LOGGING ---
            try:
                idx_search = current if schedule.index.tz else current.replace(tzinfo=None)
                debug_row = schedule.loc[idx_search]
                if isinstance(debug_row, pd.DataFrame):
                    debug_row = debug_row.iloc[0]
                price = float(debug_row.get("import_price_sek_kwh", 0))
                load = float(debug_row.get("load_forecast_kwh", 0))
                pv = float(debug_row.get("pv_forecast_kwh", 0))
                action = debug_row.get("action", "Unknown")
                chg = float(debug_row.get("battery_charge_kw", 0))
                dis = float(debug_row.get("battery_discharge_kw", 0))
                print(
                    f"{current.strftime('%H:%M')} | "
                    f"Price: {price:5.2f} kr | "
                    f"Load: {load:4.2f} kWh | "
                    f"PV: {pv:4.2f} kWh | "
                    f"SoC: {initial_state['battery_soc_percent']:5.1f}% | "
                    f"Action: {action:10} ({chg:.1f}/{dis:.1f} kW)"
                )
            except Exception as e:
                print(f"{current} | Error logging debug row: {e}")
            # ---------------------

            current += step

    finally:
        learning._learning_engine = previous_engine
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
