import os
import sys
from dataclasses import dataclass
from typing import List, Tuple

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from inputs import get_all_input_data  # type: ignore
from planner import (  # type: ignore
    HeliosPlanner,
    apply_manual_plan,
    prepare_df,
    simulate_schedule,
)
from learning import get_learning_engine, DeterministicSimulator  # type: ignore


@dataclass
class ScenarioResult:
    label: str
    export_kwh: float
    cost_sek: float
    revenue_sek: float
    wear_sek: float
    net_objective_sek: float


def _evaluate_schedule(simulator: DeterministicSimulator, df) -> Tuple[float, float, float, float]:
    """Return (cost, revenue, wear, objective) for a schedule DataFrame."""
    metrics = simulator._evaluate_schedule(df)
    cost = float(metrics.get("cost_sek", 0.0))
    revenue = float(metrics.get("revenue_sek", 0.0))
    wear = float(metrics.get("wear_sek", 0.0))
    objective = cost - revenue + wear
    return cost, revenue, wear, objective


def main() -> None:
    print("🧪 Export Scenario Explorer (full re-simulation)")

    # 1) Baseline: run full planner schedule once
    input_data = get_all_input_data("config.yaml")
    planner = HeliosPlanner("config.yaml")
    baseline_df = planner.generate_schedule(input_data)

    # Focus on future slots for evaluation
    future_mask = ~baseline_df.get("is_historical", False)
    baseline_future = baseline_df[future_mask]
    if baseline_future.empty:
        print("No future slots found in baseline schedule; nothing to simulate.")
        return

    # Learning engine's deterministic simulator provides the cashflow model
    engine = get_learning_engine()
    simulator = DeterministicSimulator(engine)

    base_cost, base_rev, base_wear, base_obj = _evaluate_schedule(simulator, baseline_future)
    base_export = float(baseline_future.get("export_kwh", 0.0).sum())

    print(
        f"Baseline objective: cost={base_cost:.2f} SEK, revenue={base_rev:.2f} SEK, "
        f"wear={base_wear:.2f} SEK, net={base_obj:.2f} SEK"
    )
    print(f"Baseline future export energy: {base_export:.2f} kWh\n")

    # 2) Identify the highest-price future slot
    peak_idx = baseline_future["import_price_sek_kwh"].idxmax()
    peak_row = baseline_future.loc[peak_idx]
    peak_start = peak_row.get("start_time")
    peak_end = peak_row.get("end_time")
    peak_price = float(peak_row.get("import_price_sek_kwh") or 0.0)

    print(f"Peak slot (local): {peak_start} → {peak_end} @ {peak_price:.3f} SEK/kWh\n")

    # 3) Scenarios: force an Export block at the peak slot and re-simulate via simulate_schedule
    config = engine.config
    timezone = config.get("timezone", "Europe/Stockholm")
    initial_state = input_data.get("initial_state") or {}

    df_inputs = prepare_df(input_data, tz_name=timezone)
    if df_inputs.empty:
        print("Input DF is empty; cannot run simulate_schedule.")
        return

    scenarios: List[ScenarioResult] = []

    # We test an increasing "strength" of export hint by duplicating the Export block;
    # the planner will still respect device limits and safety guards internally.
    for n_blocks in (1, 2, 3, 4):
        manual_plan = {
            "plan": [
                {
                    "id": f"export-peak-{n_blocks}",
                    "group": "export",
                    "action": "Export",
                    "start": peak_start,
                    "end": peak_end,
                }
            ]
        }

        df_manual = apply_manual_plan(df_inputs, manual_plan, config)
        sim_df = simulate_schedule(df_manual, config, initial_state)

        sim_cost, sim_rev, sim_wear, sim_obj = _evaluate_schedule(simulator, sim_df)
        sim_export = float(sim_df.get("export_kwh", 0.0).sum())

        scenarios.append(
            ScenarioResult(
                label=f"Export block x{n_blocks} at peak",
                export_kwh=sim_export,
                cost_sek=sim_cost,
                revenue_sek=sim_rev,
                wear_sek=sim_wear,
                net_objective_sek=sim_obj,
            )
        )

    print("Scenario comparison (full-horizon objective vs baseline):")
    print("---------------------------------------------------------")
    print(
        f"{'Scenario':32}  {'Export [kWh]':>12}  {'Net [SEK]':>11}  "
        f"{'Δ vs baseline [SEK]':>20}"
    )
    for s in scenarios:
        delta = base_obj - s.net_objective_sek
        print(
            f"{s.label:32}  {s.export_kwh:12.2f}  {s.net_objective_sek:11.2f}  {delta:20.2f}"
        )


if __name__ == "__main__":
    main()

