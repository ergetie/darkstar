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
        
        # SoC state variables (T+1 states for T slots)
        # Bounds are enforced by constraints, but we can set hard bounds here too
        min_soc_kwh = config.capacity_kwh * config.min_soc_percent / 100.0
        max_soc_kwh = config.capacity_kwh * config.max_soc_percent / 100.0
        
        soc = pulp.LpVariable.dicts(
            "soc_kwh", 
            range(T + 1), 
            lowBound=min_soc_kwh, 
            upBound=max_soc_kwh
        )

        # Initial SoC Constraint
        # Clamp initial SoC to bounds to avoid immediate infeasibility
        initial_soc = max(min_soc_kwh, min(max_soc_kwh, input_data.initial_soc_kwh))
        prob += soc[0] == initial_soc

        # Objective Function Terms
        total_cost = []

        for t in range(T):
            s = slots[t]
            h = slot_hours[t]
            
            # 1. Energy Balance Constraint
            # Load + Charge + Export = PV + Discharge + Import
            prob += (
                s.load_kwh + charge[t] + grid_export[t] 
                == s.pv_kwh + discharge[t] + grid_import[t]
            )

            # 2. Battery Dynamics Constraint
            # SoC[t+1] = SoC[t] + (Charge * eff_c) - (Discharge / eff_d)
            # Note: Efficiency is usually applied such that you pay more to charge or get less from discharge.
            # Standard model: 
            #   Stored = Charge * eff_c
            #   Released = Discharge / eff_d  (requires more stored energy to release X)
            #   OR Released = Discharge * eff_d (if Discharge is "energy leaving battery")
            
            # Let's stick to the definition where charge/discharge variables are "energy at the inverter/grid side".
            # If charge[t] is energy FROM grid/pv INTO system -> Battery receives charge[t] * eff_c
            # If discharge[t] is energy FROM system TO grid/load -> Battery loses discharge[t] / eff_d
            
            # However, in the prototype `milp_solver.py`, it was:
            # soc[t+1] == soc[t] + charge[t] - discharge[t] (Ideal battery)
            # The config has `charge_efficiency` and `discharge_efficiency`.
            # Let's implement the efficiency model.
            
            # If eff=1.0, it simplifies to ideal.
            # If eff=0.95 roundtrip, maybe sqrt(0.95) each way.
            
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

            # 4. Objective Terms
            # Cost = Import * Price - Export * Price + Wear Cost
            # Wear cost is usually applied to throughput (charge + discharge)
            
            # Use export price if available, else import price (net metering / fallback)
            # But usually export price is distinct.
            
            # Note: In prototype, wear cost was applied to (charge + discharge).
            # We will stick to that.
            
            slot_wear_cost = (charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh
            slot_import_cost = grid_import[t] * s.import_price_sek_kwh
            slot_export_revenue = grid_export[t] * s.export_price_sek_kwh
            
            total_cost.append(slot_import_cost - slot_export_revenue + slot_wear_cost)

        # Terminal SoC Constraint
        # Use target_soc_kwh if provided, otherwise enforce "End where you started"
        target_soc = config.target_soc_kwh if config.target_soc_kwh is not None else initial_soc
        prob += soc[T] >= target_soc

        # Set Objective
        prob += pulp.lpSum(total_cost)

        # Solve
        # msg=False to suppress stdout
        prob.solve(pulp.PULP_CBC_CMD(msg=False))

        # Extract Results
        status = pulp.LpStatus[prob.status]
        is_optimal = (status == "Optimal")
        
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
                    is_optimal=True
                ))
        
        return KeplerResult(
            slots=result_slots,
            total_cost_sek=final_total_cost,
            is_optimal=is_optimal,
            status_msg=status
        )
