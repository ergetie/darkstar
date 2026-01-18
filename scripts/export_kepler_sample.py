from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import json  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from planner.solver.types import KeplerConfig, KeplerInput, KeplerInputSlot  # noqa: E402


def export_sample():
    start = datetime(2025, 1, 1, 0, 0)
    slots = []

    # 48 hours (192 slots)
    for i in range(192):
        s = start + timedelta(minutes=15 * i)
        e = s + timedelta(minutes=15)

        hour = s.hour
        is_cheap = 0 <= hour <= 5
        import_price = 0.2 if is_cheap else 1.5

        slots.append(
            KeplerInputSlot(
                start_time=s,
                end_time=e,
                load_kwh=0.25,  # 0.5 kW
                pv_kwh=1.0 if 10 <= hour <= 15 else 0.0,
                import_price_sek_kwh=import_price,
                export_price_sek_kwh=import_price - 0.1,
            )
        )

    input_data = KeplerInput(slots=slots, initial_soc_kwh=5.0)
    config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=90.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.05,
        terminal_value_sek_kwh=0.5,
        # Water enabled with spacing
        water_heating_power_kw=3.0,
        water_heating_min_kwh=5.0,
        water_min_spacing_hours=4.0,
        water_block_start_penalty_sek=0.5,
    )

    # Use the SidecarInput format
    sidecar_data = {
        "input": {
            "slots": [
                {
                    "start_time": s.start_time.isoformat() + "Z",
                    "end_time": s.end_time.isoformat() + "Z",
                    "load_kwh": s.load_kwh,
                    "pv_kwh": s.pv_kwh,
                    "import_price_sek_kwh": s.import_price_sek_kwh,
                    "export_price_sek_kwh": s.export_price_sek_kwh,
                }
                for s in input_data.slots
            ],
            "initial_soc_kwh": input_data.initial_soc_kwh,
        },
        "config": {
            "capacity_kwh": config.capacity_kwh,
            "min_soc_percent": config.min_soc_percent,
            "max_soc_percent": config.max_soc_percent,
            "max_charge_power_kw": config.max_charge_power_kw,
            "max_discharge_power_kw": config.max_discharge_power_kw,
            "charge_efficiency": config.charge_efficiency,
            "discharge_efficiency": config.discharge_efficiency,
            "wear_cost_sek_per_kwh": config.wear_cost_sek_per_kwh,
            "max_export_power_kw": config.max_export_power_kw,
            "max_import_power_kw": config.max_import_power_kw,
            "target_soc_kwh": config.target_soc_kwh,
            "target_soc_penalty_sek": config.target_soc_penalty_sek,
            "terminal_value_sek_kwh": config.terminal_value_sek_kwh,
            "ramping_cost_sek_per_kw": config.ramping_cost_sek_per_kw,
            "export_threshold_sek_per_kwh": config.export_threshold_sek_per_kwh,
            "grid_import_limit_kw": config.grid_import_limit_kw,
            "water_heating_power_kw": config.water_heating_power_kw,
            "water_heating_min_kwh": config.water_heating_min_kwh,
            "water_heating_max_gap_hours": config.water_heating_max_gap_hours,
            "water_heated_today_kwh": config.water_heated_today_kwh,
            "water_comfort_penalty_sek": config.water_comfort_penalty_sek,
            "water_min_spacing_hours": config.water_min_spacing_hours,
            "water_spacing_penalty_sek": config.water_spacing_penalty_sek,
            "force_water_on_slots": config.force_water_on_slots,
            "water_block_start_penalty_sek": config.water_block_start_penalty_sek,
            "defer_up_to_hours": config.defer_up_to_hours,
            "enable_export": config.enable_export,
        },
    }

    output_path = Path("experimental/rust_solver/sample.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(sidecar_data, f, indent=2)

    print(f"Sample exported to {output_path}")


if __name__ == "__main__":
    export_sample()
