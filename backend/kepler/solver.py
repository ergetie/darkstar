import pulp
from typing import List
from .types import KeplerConfig, KeplerInput, KeplerResult, KeplerResultSlot

class KeplerSolver:
    def solve(self, input_data: KeplerInput, config: KeplerConfig) -> KeplerResult:
        """
        Solve the energy scheduling problem using MILP.
        """
        slots = input_data.slots
        T = len(slots)
        if T == 0:
            return KeplerResult(slots=[], total_cost_sek=0.0, is_optimal=True, status_msg="No slots to schedule")
            
        if T == 0:
            return KeplerResult(slots=[], total_cost_sek=0.0, is_optimal=True, status_msg="No slots to schedule")
            
        # Calculate slot duration in hours (assuming uniform for now, but robust to variable)
        # We'll calculate it per slot to be safe
        slot_hours = []
        for s in slots:
            duration = (s.end_time - s.start_time).total_seconds() / 3600.0
            slot_hours.append(duration)

        # Problem Definition
        prob = pulp.LpProblem("KeplerSchedule", pulp.LpMinimize)

        # Variables
        # All in kWh per slot (energy) or kWh (state)
        charge = pulp.LpVariable.dicts("charge_kwh", range(T), lowBound=0.0)
        discharge = pulp.LpVariable.dicts("discharge_kwh", range(T), lowBound=0.0)
        grid_import = pulp.LpVariable.dicts("import_kwh", range(T), lowBound=0.0)
        grid_export = pulp.LpVariable.dicts("export_kwh", range(T), lowBound=0.0)
        curtailment = pulp.LpVariable.dicts("curtailment_kwh", range(T), lowBound=0.0)
        load_shedding = pulp.LpVariable.dicts("load_shedding_kwh", range(T), lowBound=0.0)
        
        # SoC state variables (T+1 states for T slots)
        # Bounds: 0 to Capacity. Min/Max SoC are enforced by soft constraints.
        min_soc_kwh = config.capacity_kwh * config.min_soc_percent / 100.0
        max_soc_kwh = config.capacity_kwh * config.max_soc_percent / 100.0
        
        soc = pulp.LpVariable.dicts(
            "soc_kwh", 
            range(T + 1), 
            lowBound=0.0, 
            upBound=config.capacity_kwh
        )
        
        # Slack variables for Min SoC violation
        soc_violation = pulp.LpVariable.dicts("soc_violation_kwh", range(T + 1), lowBound=0.0)

        # Ramping variables (T-1 transitions)
        # We model change in net battery flow: (Charge - Discharge)
        # delta[t] = (charge[t] - discharge[t]) - (charge[t-1] - discharge[t-1])
        # delta[t] = ramp_up[t] - ramp_down[t]
        ramp_up = pulp.LpVariable.dicts("ramp_up_kwh", range(T), lowBound=0.0)
        ramp_down = pulp.LpVariable.dicts("ramp_down_kwh", range(T), lowBound=0.0)

        # Initial SoC Constraint
        # We allow initial_soc to be whatever (clamped to physical bounds 0-Capacity)
        initial_soc = max(0.0, min(config.capacity_kwh, input_data.initial_soc_kwh))
        prob += soc[0] == initial_soc

        # Objective Function Terms
        total_cost = []
        
        # Penalty for violating Min SoC (e.g. 1000 SEK/kWh)
        PENALTY_SEK_PER_KWH = 1000.0
        # Penalty for curtailment (small, just to prefer using PV)
        CURTAILMENT_PENALTY = 0.1
        # Penalty for load shedding (huge, must be avoided)
        LOAD_SHEDDING_PENALTY = 10000.0

        for t in range(T):
            s = slots[t]
            h = slot_hours[t]
            
            # 1. Energy Balance Constraint
            # Load + Charge + Export + Curtailment = PV + Discharge + Import + LoadShedding
            prob += (
                s.load_kwh + charge[t] + grid_export[t] + curtailment[t]
                == s.pv_kwh + discharge[t] + grid_import[t] + load_shedding[t]
            )

            # 2. Battery Dynamics Constraint
            prob += (
                soc[t+1] == soc[t] 
                + charge[t] * config.charge_efficiency 
                - discharge[t] / (config.discharge_efficiency if config.discharge_efficiency > 0 else 1.0)
            )

            # 3. Power Limits
            # Convert kW limits to kWh for this slot duration
            max_chg_kwh = config.max_charge_power_kw * h
            max_dis_kwh = config.max_discharge_power_kw * h
            
            prob += charge[t] <= max_chg_kwh
            prob += discharge[t] <= max_dis_kwh
            
            if config.max_export_power_kw is not None:
                prob += grid_export[t] <= config.max_export_power_kw * h
            
            if config.max_import_power_kw is not None:
                prob += grid_import[t] <= config.max_import_power_kw * h

            # 4. Ramping Constraints
            # For t=0, we assume previous state was 0 flow (or we could pass initial flow)
            # Let's assume 0 flow for now to keep it simple, or ignore t=0 ramping.
            # Ignoring t=0 is safer to avoid startup penalties.
            if t > 0:
                # Flow at t: charge[t] - discharge[t]
                # Flow at t-1: charge[t-1] - discharge[t-1]
                # Diff = Flow[t] - Flow[t-1] = ramp_up - ramp_down
                prob += (
                    (charge[t] - discharge[t]) - (charge[t-1] - discharge[t-1])
                    == ramp_up[t] - ramp_down[t]
                )
            else:
                # No ramping cost for first slot transition from "unknown"
                prob += ramp_up[t] == 0
                prob += ramp_down[t] == 0

            # 5. Objective Terms
            # Cost = Import * Price - Export * (Price - Threshold) + Wear Cost + Ramping Cost
            
            slot_wear_cost = (charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh
            slot_import_cost = grid_import[t] * s.import_price_sek_kwh
            
            # Export Revenue with Hurdle Rate (Threshold)
            # If Price < Threshold, (Price - Threshold) is negative -> Cost constraint
            effective_export_price = s.export_price_sek_kwh - config.export_threshold_sek_per_kwh
            slot_export_revenue = grid_export[t] * effective_export_price
            
            # Ramping Cost (converted from SEK/kW to SEK/kWh approx or just penalty on magnitude)
            # config.ramping_cost is SEK/kW (per power change).
            # Our variables are kWh. Power = Energy / h.
            # Change in Power (kW) = (ramp_up_kwh - ramp_down_kwh) / h
            # Cost = (|Delta kW|) * cost_per_kw
            # Cost = ((ramp_up + ramp_down) / h) * cost_per_kw
            slot_ramping_cost = ((ramp_up[t] + ramp_down[t]) / h) * config.ramping_cost_sek_per_kw
            
            slot_curtailment_cost = curtailment[t] * CURTAILMENT_PENALTY
            slot_shedding_cost = load_shedding[t] * LOAD_SHEDDING_PENALTY
            
            total_cost.append(slot_import_cost - slot_export_revenue + slot_wear_cost + slot_ramping_cost + slot_curtailment_cost + slot_shedding_cost)
            
            # Soft Min SoC Constraint for t
            prob += soc[t] >= min_soc_kwh - soc_violation[t]
            
            # Soft Max SoC Constraint
            prob += soc[t] <= max_soc_kwh

        # Soft constraints for terminal state T
        prob += soc[T] >= min_soc_kwh - soc_violation[T]
        prob += soc[T] <= max_soc_kwh

        # Terminal SoC Constraint (Target)
        target_soc = config.target_soc_kwh if config.target_soc_kwh is not None else min_soc_kwh
        if config.target_soc_kwh is not None:
             prob += soc[T] >= target_soc 
        
        # Terminal Value (Soft Constraint / Incentive)
        terminal_value = soc[T] * config.terminal_value_sek_kwh
        
        # Set Objective
        prob += pulp.lpSum(total_cost) - terminal_value + PENALTY_SEK_PER_KWH * pulp.lpSum(soc_violation)

        # Solve
        # msg=False to suppress stdout
        prob.solve(pulp.PULP_CBC_CMD(msg=False))

        # Extract Results
        status = pulp.LpStatus[prob.status]
        is_optimal = (status == "Optimal")
        
        if not is_optimal:
            prob.writeLP("kepler_debug.lp")
            print(f"Solver failed: {status}. LP written to kepler_debug.lp")

        result_slots = []
        final_total_cost = 0.0
        
        if is_optimal:
            for t in range(T):
                s = slots[t]
                
                # Extract values
                c_val = pulp.value(charge[t])
                d_val = pulp.value(discharge[t])
                i_val = pulp.value(grid_import[t])
                e_val = pulp.value(grid_export[t])
                soc_val = pulp.value(soc[t+1]) # SoC at end of slot
                
                # Calculate cost for this slot based on realized values
                wear = (c_val + d_val) * config.wear_cost_sek_per_kwh
                cost = (i_val * s.import_price_sek_kwh) - (e_val * s.export_price_sek_kwh) + wear
                final_total_cost += cost
                
                result_slots.append(KeplerResultSlot(
                    start_time=s.start_time,
                    end_time=s.end_time,
                    charge_kwh=c_val,
                    discharge_kwh=d_val,
                    grid_import_kwh=i_val,
                    grid_export_kwh=e_val,
                    soc_kwh=soc_val,
                    cost_sek=cost,
                    import_price_sek_kwh=s.import_price_sek_kwh,
                    export_price_sek_kwh=s.export_price_sek_kwh,
                    is_optimal=True
                ))
        
        return KeplerResult(
            slots=result_slots,
            total_cost_sek=final_total_cost,
            is_optimal=is_optimal,
            status_msg=status
        )
