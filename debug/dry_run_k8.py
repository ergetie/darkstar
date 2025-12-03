import pandas as pd
import yaml
from backend.kepler.solver import KeplerSolver
from backend.kepler.types import KeplerInput, KeplerInputSlot, KeplerConfig
from datetime import datetime, timedelta

def run_test():
    print("🚀 Running K8 Grid Peak Shaving Test...")
    
    # 1. Setup Config with Low Grid Limit
    config = KeplerConfig(
        capacity_kwh=10.0,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.10,
        grid_import_limit_kw=2.0,  # <--- LOW LIMIT (2kW)
        target_soc_kwh=5.0
    )
    
    # 2. Setup Input with High Load (5kW) > Limit (2kW)
    # This forces the battery to discharge 3kW to stay under the limit.
    now = datetime.now()
    slots = []
    for i in range(4): # 1 hour test
        start = now + timedelta(minutes=15*i)
        end = start + timedelta(minutes=15)
        slots.append(KeplerInputSlot(
            start_time=start,
            end_time=end,
            load_kwh=1.25, # 5kW * 0.25h = 1.25 kWh
            pv_kwh=0.0,
            import_price_sek_kwh=1.0,
            export_price_sek_kwh=1.0
        ))
        
    input_data = KeplerInput(slots=slots, initial_soc_kwh=8.0) # Start with 80% SoC
    
    # 3. Solve
    solver = KeplerSolver()
    result = solver.solve(input_data, config)
    
    # 4. Analyze
    if not result.is_optimal:
        print(f"❌ Solver failed: {result.status_msg}")
        return

    print(f"✅ Solver Optimal. Cost: {result.total_cost_sek:.2f} SEK")
    
    for s in result.slots:
        duration_h = (s.end_time - s.start_time).total_seconds() / 3600.0
        import_kw = s.grid_import_kwh / duration_h
        discharge_kw = s.discharge_kwh / duration_h
        load_kw = 5.0 # Known input
        
        print(f"Slot {s.start_time.strftime('%H:%M')}: Load={load_kw:.1f}kW, Import={import_kw:.1f}kW, Discharge={discharge_kw:.1f}kW")
        
        if import_kw > 2.01:
             print(f"   ⚠️ BREACH! Import {import_kw:.2f} > 2.0")
        elif import_kw < 1.99 and discharge_kw < 2.9:
             print(f"   ⚠️ UNDER-UTILIZED! Import {import_kw:.2f} < 2.0")
        else:
             print(f"   ✅ Capped at ~2.0kW")

if __name__ == "__main__":
    run_test()
