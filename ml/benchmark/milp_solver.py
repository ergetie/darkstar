"""
MILP-based Oracle for Antares (Rev 71).

This module defines a deterministic "Oracle" that computes a cost-optimal
daily schedule under perfect hindsight (historical load/PV/prices) and
simple battery constraints.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

try:
    import pulp
except ImportError as exc:  # pragma: no cover - dependency hint
    raise ImportError(
        "The 'pulp' package is required for the Antares Oracle MILP solver. "
        "Install it with 'pip install pulp'."
    ) from exc

from ml.simulation.data_loader import SimulationDataLoader


@dataclass
class OracleConfig:
    capacity_kwh: float
    min_soc_percent: float
    max_soc_percent: float
    max_charge_power_kw: float
    max_discharge_power_kw: float
    wear_cost_sek_per_kwh: float


def load_yaml(path: str) -> dict[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as fp:
            return yaml.safe_load(fp) or {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _load_oracle_config(config_path: str, loader: SimulationDataLoader) -> OracleConfig:
    cfg = load_yaml(config_path)
    system_cfg = cfg.get("system", {}) or {}
    battery_cfg = system_cfg.get("battery", {}) or {}
    learning_cfg = cfg.get("learning", {}) or {}

    capacity = float(battery_cfg.get("capacity_kwh", loader.battery_capacity_kwh))
    min_soc = float(battery_cfg.get("min_soc_percent", 10.0))
    max_soc = float(battery_cfg.get("max_soc_percent", 100.0))
    max_charge_kw = float(battery_cfg.get("max_charge_power_kw", 3.0))
    max_discharge_kw = float(battery_cfg.get("max_discharge_power_kw", 3.0))
    wear_cost = float(
        learning_cfg.get(
            "default_battery_cost_sek_per_kwh",
            loader.battery_cost,
        )
    )

    return OracleConfig(
        capacity_kwh=capacity,
        min_soc_percent=min_soc,
        max_soc_percent=max_soc,
        max_charge_power_kw=max_charge_kw,
        max_discharge_power_kw=max_discharge_kw,
        wear_cost_sek_per_kwh=wear_cost,
    )


def _normalize_day(day: Any) -> date:
    if isinstance(day, date) and not isinstance(day, datetime):
        return day
    if isinstance(day, datetime):
        return day.date()
    if isinstance(day, str):
        return datetime.fromisoformat(day).date()
    raise TypeError(f"Unsupported day type: {type(day)}")


def _load_day_slots(
    loader: SimulationDataLoader,
    target_day: date,
) -> pd.DataFrame:
    tz = loader.timezone
    start_dt = tz.localize(datetime.combine(target_day, datetime.min.time()))
    end_dt = start_dt + timedelta(days=1)

    query = """
        SELECT
            slot_start,
            slot_end,
            load_kwh,
            pv_kwh,
            import_price_sek_kwh,
            export_price_sek_kwh
        FROM slot_observations
        WHERE slot_start >= ? AND slot_start < ?
        ORDER BY slot_start ASC
    """
    with sqlite3.connect(loader.db_path, timeout=30.0) as conn:
        df = pd.read_sql_query(
            query,
            conn,
            params=(start_dt.isoformat(), end_dt.isoformat()),
        )

    if df.empty:
        raise RuntimeError(f"No slot_observations rows for day {target_day}")

    df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
    df["slot_end"] = pd.to_datetime(df["slot_end"], utc=True, errors="coerce")
    df = df.dropna(subset=["slot_start", "slot_end"])
    if df.empty:
        raise RuntimeError(f"No valid slot timestamps for day {target_day}")

    df["slot_start"] = df["slot_start"].dt.tz_convert(tz)
    df["slot_end"] = df["slot_end"].dt.tz_convert(tz)

    # Ensure prices and flows are numeric
    for col in ("load_kwh", "pv_kwh", "import_price_sek_kwh", "export_price_sek_kwh"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df.reset_index(drop=True)


def solve_optimal_schedule(
    day: Any,
    config_path: str = "config.yaml",
) -> pd.DataFrame:
    """
    Solve for the cost-optimal daily schedule for a given day.

    Returns a DataFrame with per-slot decision variables, SoC, and cost.
    """
    loader = SimulationDataLoader(config_path=config_path)
    oracle_cfg = _load_oracle_config(config_path, loader)

    target_day = _normalize_day(day)
    slots = _load_day_slots(loader, target_day)

    # Initial SoC from historical data
    start_dt = loader.timezone.localize(datetime.combine(target_day, datetime.min.time()))
    initial_state = loader.get_initial_state_from_history(start_dt)
    soc0_kwh = float(initial_state.get("battery_kwh", 0.0))

    capacity = oracle_cfg.capacity_kwh
    min_soc_kwh = capacity * oracle_cfg.min_soc_percent / 100.0
    max_soc_kwh = capacity * oracle_cfg.max_soc_percent / 100.0

    T = len(slots)
    slot_hours = (slots["slot_end"] - slots["slot_start"]).dt.total_seconds() / 3600.0
    # Assume uniform 15-minute slots; fallback to 0.25h if needed.
    slot_hours = slot_hours.fillna(0.25)

    prob = pulp.LpProblem("AntaresOracle", pulp.LpMinimize)

    charge = pulp.LpVariable.dicts("charge_kwh", range(T), lowBound=0.0)
    discharge = pulp.LpVariable.dicts("discharge_kwh", range(T), lowBound=0.0)
    grid_import = pulp.LpVariable.dicts("grid_import_kwh", range(T), lowBound=0.0)
    grid_export = pulp.LpVariable.dicts("grid_export_kwh", range(T), lowBound=0.0)
    soc = pulp.LpVariable.dicts(
        "soc_kwh",
        range(T + 1),
        lowBound=min_soc_kwh,
        upBound=max_soc_kwh,
    )

    # Initial SoC
    prob += soc[0] == max(min_soc_kwh, min(max_soc_kwh, soc0_kwh))

    # Constraints per slot
    for t in range(T):
        load_t = float(slots.at[t, "load_kwh"] or 0.0)
        pv_t = float(slots.at[t, "pv_kwh"] or 0.0)

        # Energy balance: load + charge + export = pv + discharge + import
        prob += load_t + charge[t] + grid_export[t] == pv_t + discharge[t] + grid_import[t]

        # Battery dynamics (simple, symmetric efficiency for now)
        slot_h = float(slot_hours.iloc[t] or 0.25)
        prob += soc[t + 1] == soc[t] + charge[t] - discharge[t]

        # Power limits
        prob += charge[t] <= oracle_cfg.max_charge_power_kw * slot_h
        prob += discharge[t] <= oracle_cfg.max_discharge_power_kw * slot_h

    # Terminal SoC constraint: end the day where we started
    prob += soc[T] == soc[0]

    # Objective: minimize net cost (import - export + wear)
    total_cost = []
    for t in range(T):
        imp_price = float(slots.at[t, "import_price_sek_kwh"] or 0.0)
        exp_price = float(
            slots.at[t, "export_price_sek_kwh"] or slots.at[t, "import_price_sek_kwh"] or 0.0
        )
        total_cost.append(grid_import[t] * imp_price)
        total_cost.append(-grid_export[t] * exp_price)
        total_cost.append((charge[t] + discharge[t]) * oracle_cfg.wear_cost_sek_per_kwh)

    prob += pulp.lpSum(total_cost)

    # Solve
    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(
            f"Oracle MILP did not find an optimal solution: {pulp.LpStatus[prob.status]}"
        )

    # Build result DataFrame
    records: list[dict[str, Any]] = []
    cumulative_cost = 0.0
    for t in range(T):
        slot = slots.iloc[t]
        slot_h = float(slot_hours.iloc[t] or 0.25)
        imp = float(grid_import[t].value() or 0.0)
        exp = float(grid_export[t].value() or 0.0)
        chg = float(charge[t].value() or 0.0)
        dis = float(discharge[t].value() or 0.0)
        soc_kwh = float(soc[t].value() or 0.0)

        imp_price = float(slot["import_price_sek_kwh"] or 0.0)
        exp_price = float(slot["export_price_sek_kwh"] or slot["import_price_sek_kwh"] or 0.0)
        wear = (chg + dis) * oracle_cfg.wear_cost_sek_per_kwh
        slot_cost = imp * imp_price - exp * exp_price + wear
        cumulative_cost += slot_cost

        records.append(
            {
                "slot_start": slot["slot_start"].isoformat(),
                "slot_end": slot["slot_end"].isoformat(),
                "load_kwh": float(slot["load_kwh"] or 0.0),
                "pv_kwh": float(slot["pv_kwh"] or 0.0),
                "import_price_sek_kwh": imp_price,
                "export_price_sek_kwh": exp_price,
                "oracle_grid_import_kwh": imp,
                "oracle_grid_export_kwh": exp,
                "oracle_charge_kwh": chg,
                "oracle_discharge_kwh": dis,
                "oracle_soc_kwh": soc_kwh,
                "oracle_soc_percent": (soc_kwh / capacity * 100.0) if capacity > 0 else 0.0,
                "oracle_slot_cost_sek": slot_cost,
                "oracle_cumulative_cost_sek": cumulative_cost,
                "slot_hours": slot_h,
            }
        )

    return pd.DataFrame(records)
