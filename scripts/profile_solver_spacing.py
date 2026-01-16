import sys
import time
import pulp
import random
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
from collections import defaultdict

# Add project root to path
sys.path.append(".")

from planner.solver.kepler import KeplerSolver, KeplerInput, KeplerConfig, KeplerResult
from planner.solver.types import KeplerResultSlot

# Mock Classes for Testing
@dataclass
class MockSlot:
    start_time: datetime
    end_time: datetime
    pv_kwh: float
    load_kwh: float
    import_price_sek_kwh: float
    export_price_sek_kwh: float

def generate_mock_data(slots: int = 96) -> KeplerInput:
    """Generate dummy data for N slots (default 48h)."""
    # Start at next midnight to ensure full days
    now = datetime.now()
    start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    mock_slots = []
    for i in range(slots):
        s_time = start + timedelta(minutes=30 * i)
        e_time = s_time + timedelta(minutes=30)
        
        # Simple sine wave patterns
        hour = s_time.hour
        is_day = 6 <= hour <= 18
        pv = 1.0 if is_day else 0.0
        load = 0.5 + (0.5 if 17 <= hour <= 21 else 0.0)
        price = 0.5 + (1.0 if 7 <= hour <= 22 else 0.0)
        
        mock_slots.append(MockSlot(
            start_time=s_time,
            end_time=e_time,
            pv_kwh=pv,
            load_kwh=load,
            import_price_sek_kwh=price,
            export_price_sek_kwh=price * 0.8
        ))
    
    return KeplerInput(
        slots=mock_slots,
        initial_soc_kwh=5.0
    )

def get_base_config() -> KeplerConfig:
    return KeplerConfig(
        capacity_kwh=10.0,
        max_charge_power_kw=5.0,
        max_discharge_power_kw=5.0,
        min_soc_percent=10.0,
        max_soc_percent=100.0,
        charge_efficiency=0.95,
        discharge_efficiency=0.95,
        wear_cost_sek_per_kwh=0.1,
        
        # Water Heater Defaults
        water_heating_power_kw=3.0,
        water_heating_min_kwh=5.0,
        water_heating_max_gap_hours=5.0,
        water_min_spacing_hours=4.0,  # The heavy constraint
        
        water_comfort_penalty_sek=10.0,
        water_spacing_penalty_sek=10.0, # Enabled
        
        # Other reqs
        target_soc_kwh=None,
        enable_export=True
    )

class OptimizedSolver(KeplerSolver):
    """Subclass with Hard Constraint optimization."""
    
    def solve(self, input_data: KeplerInput, config: KeplerConfig) -> KeplerResult:
        slots = input_data.slots
        T = len(slots)
        if T == 0:
            return KeplerResult([], 0.0, True, "No slots")

        slot_hours = []
        for s in slots:
            duration = (s.end_time - s.start_time).total_seconds() / 3600.0
            slot_hours.append(duration)

        prob = pulp.LpProblem("KeplerSchedule_Opt", pulp.LpMinimize)

        # Variables
        charge = pulp.LpVariable.dicts("charge_kwh", range(T), lowBound=0.0)
        discharge = pulp.LpVariable.dicts("discharge_kwh", range(T), lowBound=0.0)
        grid_import = pulp.LpVariable.dicts("import_kwh", range(T), lowBound=0.0)
        grid_export = pulp.LpVariable.dicts("export_kwh", range(T), lowBound=0.0)
        curtailment = pulp.LpVariable.dicts("curtailment_kwh", range(T), lowBound=0.0)
        load_shedding = pulp.LpVariable.dicts("load_shedding_kwh", range(T), lowBound=0.0)

        water_enabled = config.water_heating_power_kw > 0
        if water_enabled:
            water_heat = pulp.LpVariable.dicts("water_heat", range(T), cat="Binary")
            water_start = pulp.LpVariable.dicts("water_start", range(T), cat="Binary")
            # NO water_spacing_viol variable needed for Hard Constraint!
        else:
            water_heat = dict.fromkeys(range(T), 0)
            water_start = dict.fromkeys(range(T), 0)

        min_soc_kwh = config.capacity_kwh * config.min_soc_percent / 100.0
        max_soc_kwh = config.capacity_kwh * config.max_soc_percent / 100.0
        soc = pulp.LpVariable.dicts("soc_kwh", range(T + 1), lowBound=0.0, upBound=config.capacity_kwh)

        soc_violation = pulp.LpVariable.dicts("soc_violation_kwh", range(T + 1), lowBound=0.0)
        target_under = pulp.LpVariable("target_under", lowBound=0.0)
        target_over = pulp.LpVariable("target_over", lowBound=0.0)
        import_breach = pulp.LpVariable.dicts("import_breach_kwh", range(T), lowBound=0.0)
        ramp_up = pulp.LpVariable.dicts("ramp_up", range(T), lowBound=0.0)
        ramp_down = pulp.LpVariable.dicts("ramp_down", range(T), lowBound=0.0)

        initial_soc = max(0.0, min(config.capacity_kwh, input_data.initial_soc_kwh))
        prob += soc[0] == initial_soc

        total_cost = []
        
        # Helper map
        slots_ref = slots # local access

        for t in range(T):
            s = slots_ref[t]
            h = slot_hours[t]
            
            w_load = water_heat[t] * config.water_heating_power_kw * h if water_enabled else 0
            
            # Balance
            prob += (s.load_kwh + w_load + charge[t] + grid_export[t] + curtailment[t] 
                     == s.pv_kwh + discharge[t] + grid_import[t] + load_shedding[t])
            
            # Water Start
            if water_enabled:
                if t == 0:
                    prob += water_start[t] == water_heat[t]
                else:
                    prob += water_start[t] >= water_heat[t] - water_heat[t-1]
            
            # Battery Logic
            prob += soc[t + 1] == soc[t] + charge[t] * config.charge_efficiency - discharge[t] / config.discharge_efficiency

            # Limits
            prob += charge[t] <= config.max_charge_power_kw * h
            prob += discharge[t] <= config.max_discharge_power_kw * h
            if config.max_export_power_kw: prob += grid_export[t] <= config.max_export_power_kw * h
            if config.max_import_power_kw: prob += grid_import[t] <= config.max_import_power_kw * h
            if config.grid_import_limit_kw: prob += grid_import[t] <= config.grid_import_limit_kw * h + import_breach[t]
            if not config.enable_export: prob += grid_export[t] == 0
            
            # Costs
            cost = (
                (charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh +
                grid_import[t] * s.import_price_sek_kwh -
                grid_export[t] * (s.export_price_sek_kwh - config.export_threshold_sek_per_kwh) +
                import_breach[t] * 5000.0 +
                load_shedding[t] * 10000.0
            )
            total_cost.append(cost)
            
            # Soft SoC
            prob += soc[t] >= min_soc_kwh - soc_violation[t]
            prob += soc[t] <= max_soc_kwh

        # Terminal
        prob += soc[T] >= min_soc_kwh - soc_violation[T]
        prob += soc[T] <= max_soc_kwh
        
        # Target SoC
        if config.target_soc_kwh is not None:
             prob += soc[T] >= config.target_soc_kwh - target_under
             prob += soc[T] <= config.target_soc_kwh + target_over
             total_cost.append(config.target_soc_penalty_sek * target_under)
             if config.target_soc_kwh > 0:
                 total_cost.append(config.target_soc_penalty_sek * target_over)

        # --- WATER HEATING OPTIMIZED ---
        if water_enabled:
            # Min kWh per day (simplified from original for brevity, assuming full days)
            # Just implement the global min spacing for benchmark
            avg_slot_hours = sum(slot_hours) / len(slot_hours)
            
            # 1. Daily Needs (Simplified: just total need for benchmark duration?)
            # No, lets stick to the loop structure if possible or just simplified.
            # To be fair, we must include the daily constraints otherwise problem is easier.
            # Copying daily loop roughly.
            water_kwh_per_slot = config.water_heating_power_kw * avg_slot_hours
            defer_hours = config.defer_up_to_hours
            slots_by_day = defaultdict(list)
            for t in range(T):
                dt = slots[t].start_time
                bucket = dt.date()
                if defer_hours > 0 and dt.hour < defer_hours:
                    bucket -= timedelta(days=1)
                slots_by_day[bucket].append(t)
            
            for i, day in enumerate(sorted(slots_by_day.keys())):
                indices = slots_by_day[day]
                req = config.water_heating_min_kwh
                if i == 0: 
                    req = max(0, req - config.water_heated_today_kwh)
                prob += pulp.lpSum(water_heat[t] for t in indices) * water_kwh_per_slot >= req

            # 2. Hard Spacing Constraint (The Optimization)
            if config.water_min_spacing_hours > 0:
                 spacing_slots = max(1, int(config.water_min_spacing_hours / avg_slot_hours))
                 M = spacing_slots
                 for t in range(T):
                     start_idx = max(0, t - spacing_slots)
                     # If we start at t, previous window sum must be 0
                     prob += (
                         pulp.lpSum(water_heat[j] for j in range(start_idx, t)) 
                         + water_start[t] * M 
                         <= M
                     )

        # Objective
        term_val = soc[T] * config.terminal_value_sek_kwh
        prob += pulp.lpSum(total_cost) - term_val + 1000.0 * pulp.lpSum(soc_violation)

        prob.solve(pulp.PULP_CBC_CMD(msg=False))
        
        status = pulp.LpStatus[prob.status]
        is_optimal = status == "Optimal"
        
        cost_val = 0.0
        res_slots = []
        if is_optimal:
            for t in range(T):
                w_kw = config.water_heating_power_kw if pulp.value(water_heat[t]) > 0.5 else 0.0
                res_slots.append(KeplerResultSlot(
                    slots[t].start_time, slots[t].end_time, 
                    0,0,0,0,0,0, # dummies
                    water_heat_kw=w_kw
                ))
                
        return KeplerResult(res_slots, pulp.value(prob.objective), is_optimal, status)

def benchmark(name: str, config: KeplerConfig, input_data: KeplerInput):
    print(f"--- Benchmarking: {name} ---")
    solver = KeplerSolver()
    
    t0 = time.time()
    result = solver.solve(input_data, config)
    duration = time.time() - t0
    
    print(f"Duration: {duration:.4f}s")
    print(f"Optimal: {result.is_optimal}")
    print(f"Cost: {result.total_cost_sek:.2f}")
    if result.is_optimal:
        # Count water slots
        w_slots = sum(1 for s in result.slots if s.water_heat_kw > 0)
        print(f"Water Blocks: {w_slots}")
    print("-" * 30)
    return duration

if __name__ == "__main__":
    print("Generating Data...")
    data = generate_mock_data(slots=96) # 48 hours
    
    # 1. Baseline
    cfg_base = get_base_config()
    benchmark("Baseline (Pairwise Spacing)", cfg_base, data)
    
    # 2. No Spacing
    cfg_none = get_base_config()
    cfg_none.water_spacing_penalty_sek = 0 # Disable
    benchmark("Control (No Spacing)", cfg_none, data)
    
    # 3. Reduce Window (2h)
    cfg_short = get_base_config()
    cfg_short.water_min_spacing_hours = 2.0 
    benchmark("Short Window (2h)", cfg_short, data)

    # 4. Optimized (Hard Constraint)
    cfg_opt = get_base_config()
    print(f"--- Benchmarking: Optimized (Hard Constraint) ---")
    solver = OptimizedSolver()
    t0 = time.time()
    result = solver.solve(data, cfg_opt)
    duration = time.time() - t0
    print(f"Duration: {duration:.4f}s")
    print(f"Optimal: {result.is_optimal}")
    if result.is_optimal:
        w_slots = sum(1 for s in result.slots if s.water_heat_kw > 0)
        print(f"Water Blocks: {w_slots}")
    print("-" * 30)

