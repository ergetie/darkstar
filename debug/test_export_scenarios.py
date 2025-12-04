import copy
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple

import pandas as pd

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from planner_legacy import (  # type: ignore
    apply_manual_plan,
    prepare_df,
    simulate_schedule,
)
from learning import get_learning_engine, DeterministicSimulator  # type: ignore


@dataclass
class ScenarioResult:
    label: str
    target_export_kwh: float
    realized_export_kwh: float
    cost_sek: float
    revenue_sek: float
    wear_sek: float
    net_objective_sek: float


def _evaluate_schedule(
    simulator: DeterministicSimulator, df: pd.DataFrame
) -> Tuple[float, float, float, float]:
    """Return (cost, revenue, wear, objective) for a schedule DataFrame."""
    metrics = simulator._evaluate_schedule(df)
    cost = float(metrics.get("cost_sek", 0.0))
    revenue = float(metrics.get("revenue_sek", 0.0))
    wear = float(metrics.get("wear_sek", 0.0))
    objective = cost - revenue + wear
    return cost, revenue, wear, objective


def _build_sim_config(engine) -> dict:
    """Return a deep-copied config with more permissive manual export settings."""
    config = copy.deepcopy(engine.config)

    system_batt = config.get("system", {}).get("battery", {}) or {}
    legacy_batt = config.get("battery", {}) or {}
    min_soc_percent = float(
        system_batt.get("min_soc_percent")
        or legacy_batt.get("min_soc_percent")
        or 15.0
    )

    manual = config.setdefault("manual_planning", {})
    manual.setdefault("export_target_percent", min_soc_percent)
    manual.setdefault("override_hold_in_cheap", True)
    manual.setdefault("force_discharge_on_deficit", True)

    return config


def main() -> None:
    print("🧪 Export Scenario Explorer (full-day re-simulation, multi-slot)")

    # 1) Build baseline inputs for TODAY (00:00–24:00) from learning DB
    engine = get_learning_engine()
    simulator = DeterministicSimulator(engine)
    sim_config = _build_sim_config(engine)
    timezone = sim_config.get("timezone", "Europe/Stockholm")
    today = datetime.now(engine.timezone).date()

    input_data = simulator._build_input_data_for_day(today)
    if not input_data:
        print(f"No historical price/forecast data found for {today}; aborting.")
        return

    initial_state = input_data.get("initial_state") or {}

    df_inputs = prepare_df(input_data, tz_name=timezone)
    if df_inputs.empty:
        print("Input DF is empty; cannot run simulate_schedule.")
        return

    # Baseline schedule via simulate_schedule with an empty manual plan
    baseline_input_df = apply_manual_plan(df_inputs, {"plan": []}, sim_config)
    baseline_df = simulate_schedule(baseline_input_df, sim_config, initial_state)
    base_cost, base_rev, base_wear, base_obj = _evaluate_schedule(simulator, baseline_df)
    base_export = float(baseline_df.get("export_kwh", 0.0).sum())

    print(
        f"Baseline objective: cost={base_cost:.2f} SEK, revenue={base_rev:.2f} SEK, "
        f"wear={base_wear:.2f} SEK, net={base_obj:.2f} SEK"
    )
    print(f"Baseline export energy (simulated horizon): {base_export:.2f} kWh\n")

    # 2) Rank future slots by price (highest first)
    slots_sorted = baseline_df.sort_values("import_price_sek_kwh", ascending=False)
    if slots_sorted.empty:
        print("No slots with prices; aborting.")
        return

    # 3) Scenarios: target export energies; fill across multiple price slots if needed
    target_kwh_values = [2.0, 4.0, 6.0, 10.0]
    scenarios: List[ScenarioResult] = []

    for target_kwh in target_kwh_values:
        chosen_indices: List[pd.Timestamp] = []
        best_export = 0.0
        best_cost = base_cost
        best_rev = base_rev
        best_wear = base_wear
        best_obj = base_obj

        # Greedily add slots in descending price order until the planner actually
        # exports close to the requested target_kwh or we run out of slots.
        for idx in slots_sorted.index:
            chosen_indices.append(idx)

            plan_entries = []
            for ci in chosen_indices:
                row = baseline_df.loc[ci]
                start = row.get("start_time", ci)
                end = row.get("end_time")
                plan_entries.append(
                    {
                        "id": f"export-{ci.isoformat()}",
                        "group": "export",
                        "action": "Export",
                        "start": start,
                        "end": end,
                    }
                )

            manual_plan = {"plan": plan_entries}
            df_manual = apply_manual_plan(df_inputs, manual_plan, sim_config)
            sim_df = simulate_schedule(df_manual, sim_config, initial_state)
            sim_cost, sim_rev, sim_wear, sim_obj = _evaluate_schedule(simulator, sim_df)
            sim_export = float(sim_df.get("export_kwh", 0.0).sum())

            # Track the best approximation to the target so far
            if sim_export > best_export:
                best_export = sim_export
                best_cost, best_rev, best_wear, best_obj = sim_cost, sim_rev, sim_wear, sim_obj

            # Stop if we're within 10% of the target
            if sim_export >= target_kwh * 0.9:
                break

        scenarios.append(
            ScenarioResult(
                label=f"Target ≈ {target_kwh:g} kWh across peaks",
                target_export_kwh=target_kwh,
                realized_export_kwh=best_export,
                cost_sek=best_cost,
                revenue_sek=best_rev,
                wear_sek=best_wear,
                net_objective_sek=best_obj,
            )
        )

    print("Scenario comparison (full-horizon objective vs baseline):")
    print("---------------------------------------------------------")
    print(
        f"{'Scenario':32}  {'Target [kWh]':>12}  {'Realized [kWh]':>15}  "
        f"{'Net [SEK]':>11}  {'Δ vs baseline [SEK]':>20}"
    )
    for s in scenarios:
        delta = base_obj - s.net_objective_sek
        print(
            f"{s.label:32}  {s.target_export_kwh:12.2f}  {s.realized_export_kwh:15.2f}  "
            f"{s.net_objective_sek:11.2f}  {delta:20.2f}"
        )


if __name__ == "__main__":
    main()
