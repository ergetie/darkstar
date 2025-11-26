import os
import sys
from dataclasses import dataclass
from typing import List

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
    delivered_kwh: float
    revenue_sek: float
    recharge_cost_sek: float
    wear_cost_sek: float
    net_gain_sek: float


def _compute_protective_soc_kwh(planner: HeliosPlanner) -> float:
    """Recompute protective SoC floor (kWh) using the planner's own config."""
    cfg = planner.config
    battery = planner.battery_config
    arbitrage = cfg.get("arbitrage", {}) or {}

    capacity_kwh = float(battery.get("capacity_kwh", 10.0))
    min_soc_percent = float(battery.get("min_soc_percent", 15.0))
    min_soc_kwh = capacity_kwh * (min_soc_percent / 100.0)

    protective_soc_strategy = arbitrage.get("protective_soc_strategy", "gap_based")
    fixed_protective_soc_percent = float(arbitrage.get("fixed_protective_soc_percent", 15.0))

    if protective_soc_strategy == "gap_based":
        future_responsibilities = sum(
            float(resp.get("total_responsibility_kwh", 0.0))
            for resp in getattr(planner, "window_responsibilities", [])
        )
        protective_soc_kwh = max(min_soc_kwh, future_responsibilities * 1.1)
    else:
        protective_soc_kwh = capacity_kwh * (fixed_protective_soc_percent / 100.0)

    return protective_soc_kwh


def main() -> None:
    print("🧪 Export Scenario Explorer")

    # 1) Run planner once to get current schedule and prices
    input_data = get_all_input_data("config.yaml")
    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data)

    # Focus on future slots (from now_slot onward)
    now_slot = getattr(planner, "now_slot", None)
    if now_slot is not None:
        df_future = df[df.index >= now_slot]
    else:
        df_future = df

    if df_future.empty:
        print("No future slots found; nothing to simulate.")
        return

    # 2) Identify the main peak slot (highest import price)
    peak_idx = df_future["import_price_sek_kwh"].idxmax()
    peak_row = df_future.loc[peak_idx]

    peak_price_import = float(peak_row.get("import_price_sek_kwh") or 0.0)
    peak_price_export = float(peak_row.get("export_price_sek_kwh") or peak_price_import)
    peak_start = peak_row.get("start_time")

    print(f"Peak slot: {peak_start}  price={peak_price_import:.3f} SEK/kWh")

    # 3) Compute safety and device limits
    capacity_kwh = float(planner.battery_config.get("capacity_kwh", 10.0))
    min_soc_percent_cfg = float(planner.battery_config.get("min_soc_percent", 15.0))
    min_soc_kwh = capacity_kwh * (min_soc_percent_cfg / 100.0)
    max_discharge_kw = float(planner.battery_config.get("max_discharge_power_kw", 5.0))
    slot_length_h = 0.25  # 15 minutes
    slot_discharge_cap_kwh = max_discharge_kw * slot_length_h

    soc_percent_peak = float(peak_row.get("projected_soc_percent") or 0.0)
    soc_kwh_peak = capacity_kwh * (soc_percent_peak / 100.0)

    protective_soc_kwh = _compute_protective_soc_kwh(planner)
    roundtrip_eff = getattr(planner, "roundtrip_efficiency", 0.95) or 0.95
    discharge_eff = getattr(planner, "discharge_efficiency", 0.97) or 0.97
    battery_cycle_cost = float(planner.battery_economics.get("battery_cycle_cost_kwh", 0.0))

    print(f"SoC at peak: {soc_kwh_peak:.2f} kWh ({soc_percent_peak:.1f}%)")
    print(f"Min SoC floor: {min_soc_kwh:.2f} kWh  ·  Protective floor (planner): {protective_soc_kwh:.2f} kWh")

    # 4) Build list of future slots after the peak, sorted by increasing price (for recharge)
    future_after_peak = df_future[df_future.index > peak_idx]
    if future_after_peak.empty:
        print("No slots after peak; cannot simulate recharge.")
        return

    future_sorted = future_after_peak.sort_values("import_price_sek_kwh")

    # 5) Scenarios: different export energy amounts in the peak slot (delivered kWh)
    scenarios_kwh = [2.0, 4.0, 6.0, 10.0]
    results: List[ScenarioResult] = []

    for energy_kwh in scenarios_kwh:
        # Respect slot discharge limit (delivered kWh) and SoC safety.
        # For this what-if, we only enforce the configured min SoC floor,
        # not the more conservative protective export floor.
        headroom_kwh = max(0.0, soc_kwh_peak - min_soc_kwh)
        max_deliverable_from_headroom = headroom_kwh * discharge_eff
        deliverable_kwh = min(energy_kwh, slot_discharge_cap_kwh, max_deliverable_from_headroom)

        if deliverable_kwh <= 0.0:
            results.append(
                ScenarioResult(
                    label=f"Export {energy_kwh:g} kWh at peak",
                    forced_export_kwh=energy_kwh,
                    delivered_kwh=0.0,
                    revenue_sek=0.0,
                    recharge_cost_sek=0.0,
                    wear_cost_sek=0.0,
                    net_gain_sek=0.0,
                )
            )
            continue

        # Revenue from export at peak
        revenue = deliverable_kwh * peak_price_export

        # Energy we need to buy back from the grid (kWh at meter) to restore the battery
        # Roughly: delivered energy / roundtrip_eff
        grid_energy_needed = deliverable_kwh / max(roundtrip_eff, 1e-6)

        remaining = grid_energy_needed
        recharge_cost = 0.0
        charge_eff = getattr(planner, "charge_efficiency", roundtrip_eff) or roundtrip_eff

        for _, row in future_sorted.iterrows():
            price = float(row.get("import_price_sek_kwh") or 0.0)
            # Max battery energy per slot from grid at device limit
            slot_batt_cap_kwh = max_discharge_kw * slot_length_h  # use same kW cap for simplicity
            slot_grid_cap_kwh = slot_batt_cap_kwh / max(charge_eff, 1e-6)

            take = min(remaining, slot_grid_cap_kwh)
            if take <= 0:
                continue

            recharge_cost += take * price
            remaining -= take
            if remaining <= 1e-6:
                break

        # Battery wear
        wear_cost = deliverable_kwh * battery_cycle_cost

        net_gain = revenue - recharge_cost - wear_cost

        results.append(
            ScenarioResult(
                label=f"Export {energy_kwh:g} kWh at peak",
                forced_export_kwh=energy_kwh,
                delivered_kwh=deliverable_kwh,
                revenue_sek=revenue,
                recharge_cost_sek=recharge_cost,
                wear_cost_sek=wear_cost,
                net_gain_sek=net_gain,
            )
        )

    print("\nScenario comparison (net gain vs no extra export):")
    print("---------------------------------------------------")
    print(
        f"{'Scenario':32}  {'Delivered [kWh]':>14}  {'Revenue [SEK]':>14}  "
        f"{'Recharge [SEK]':>15}  {'Wear [SEK]':>11}  {'Net gain [SEK]':>16}"
    )
    for r in results:
        print(
            f"{r.label:32}  {r.delivered_kwh:14.2f}  {r.revenue_sek:14.2f}  "
            f"{r.recharge_cost_sek:15.2f}  {r.wear_cost_sek:11.2f}  {r.net_gain_sek:16.2f}"
        )


if __name__ == "__main__":
    main()
