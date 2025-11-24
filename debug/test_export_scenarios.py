import json
import os
import sys
from dataclasses import dataclass
from typing import List

import yaml

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

from inputs import get_all_input_data  # type: ignore
from planner import HeliosPlanner  # type: ignore


@dataclass
class ScenarioResult:
    label: str
    forced_export_kwh: float
    net_cost_sek: float


def _run_planner(overrides: dict | None = None, manual_plan: dict | None = None) -> dict:
    input_data = get_all_input_data("config.yaml")
    planner = HeliosPlanner("config.yaml")
    schedule_df = planner.generate_schedule(input_data, overrides=overrides)

    # If a manual plan is provided, re-apply with overrides via manual_planning
    if manual_plan:
        overrides = overrides.copy() if overrides else {}
        overrides.setdefault("manual_plan", manual_plan)
        schedule_df = planner.generate_schedule(input_data, overrides=overrides)

    return schedule_df.to_dict(orient="records")


def _compute_net_cost(slots: List[dict]) -> float:
    import_cost = 0.0
    export_revenue = 0.0
    for slot in slots:
        load_kwh = float(slot.get("grid_import_kwh") or 0.0)
        export_kwh = float(slot.get("export_kwh") or 0.0)
        import_price = float(slot.get("import_price_sek_kwh") or 0.0)
        export_price = float(slot.get("export_price_sek_kwh") or import_price)

        import_cost += load_kwh * import_price
        export_revenue += export_kwh * export_price

    # Battery wear is already internalized in planner's decisions; we report
    # grid import cost minus export revenue as an external cash-flow metric.
    return import_cost - export_revenue


def _build_manual_export_plan(slots: List[dict], export_kwh: float) -> dict:
    """Create a simple manual plan that exports a fixed kWh in the peak slot.

    We pick the single future slot with the highest import price and request an
    Export block covering that 15-minute interval.
    """
    future_slots = [s for s in slots if not s.get("is_historical")]
    if not future_slots:
        raise SystemExit("No future slots found in schedule; cannot build export scenario.")

    peak = max(future_slots, key=lambda s: float(s.get("import_price_sek_kwh") or 0.0))
    start = peak.get("start_time")
    end = peak.get("end_time") or peak.get("slot_end") or start

    return {
        "plan": [
            {
                "id": "export-peak",
                "group": "export",
                "action": "Export",
                "start": start,
                "end": end,
                "kwh": export_kwh,
            }
        ]
    }


def main() -> None:
    print("🧪 Export Scenario Explorer")

    # 1) Baseline schedule
    baseline_slots = _run_planner()
    baseline_cost = _compute_net_cost(baseline_slots)
    print(f"Baseline net cost: {baseline_cost:.2f} SEK")

    # 2) Scenarios: different export energy amounts in the peak slot
    scenarios_kwh = [2.0, 4.0, 6.0, 10.0]
    results: List[ScenarioResult] = []

    for energy_kwh in scenarios_kwh:
        manual_plan = _build_manual_export_plan(baseline_slots, energy_kwh)
        slots = _run_planner(manual_plan=manual_plan)
        cost = _compute_net_cost(slots)
        label = f"Export {energy_kwh:g} kWh at peak"
        results.append(ScenarioResult(label=label, forced_export_kwh=energy_kwh, net_cost_sek=cost))

    print("\nScenario comparison (lower net cost is better):")
    print("-------------------------------------------------")
    print(f"{'Scenario':32}  {'Net cost [SEK]':>15}  {'Δ vs baseline [SEK]':>20}")
    for r in results:
        delta = baseline_cost - r.net_cost_sek
        print(f"{r.label:32}  {r.net_cost_sek:15.2f}  {delta:20.2f}")


if __name__ == "__main__":
    main()
