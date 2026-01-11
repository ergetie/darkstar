"""
Kepler MILP Solver

Mixed-Integer Linear Programming solver for optimal battery scheduling.
Migrated from backend/kepler/solver.py during Rev K13 modularization.
"""

from collections import defaultdict
from datetime import timedelta  # Rev WH2

import pulp
from .types import KeplerConfig, KeplerInput, KeplerResult, KeplerResultSlot


class KeplerSolver:
    def solve(self, input_data: KeplerInput, config: KeplerConfig) -> KeplerResult:
        """
        Solve the energy scheduling problem using MILP.
        """
        slots = input_data.slots
        T = len(slots)
        if T == 0:
            return KeplerResult(
                slots=[], total_cost_sek=0.0, is_optimal=True, status_msg="No slots to schedule"
            )

        # Calculate slot duration in hours
        slot_hours = []
        for s in slots:
            duration = (s.end_time - s.start_time).total_seconds() / 3600.0
            slot_hours.append(duration)

        # Problem Definition
        prob = pulp.LpProblem("KeplerSchedule", pulp.LpMinimize)

        # Variables (all in kWh per slot)
        charge = pulp.LpVariable.dicts("charge_kwh", range(T), lowBound=0.0)
        discharge = pulp.LpVariable.dicts("discharge_kwh", range(T), lowBound=0.0)
        grid_import = pulp.LpVariable.dicts("import_kwh", range(T), lowBound=0.0)
        grid_export = pulp.LpVariable.dicts("export_kwh", range(T), lowBound=0.0)
        curtailment = pulp.LpVariable.dicts("curtailment_kwh", range(T), lowBound=0.0)
        load_shedding = pulp.LpVariable.dicts("load_shedding_kwh", range(T), lowBound=0.0)

        # Water heating as deferrable load (Rev K17)
        water_enabled = config.water_heating_power_kw > 0
        if water_enabled:
            water_heat = pulp.LpVariable.dicts("water_heat", range(T), cat="Binary")
            # Rev K21: Spacing and transitions
            water_start = pulp.LpVariable.dicts("water_start", range(T), cat="Binary")
            water_spacing_viol = pulp.LpVariable.dicts("water_spacing_viol", range(T), cat="Binary")
        else:
            water_heat = dict.fromkeys(range(T), 0)
            water_start = dict.fromkeys(range(T), 0)
            water_spacing_viol = dict.fromkeys(range(T), 0)

        # SoC state variables (T+1 states for T slots)

        # SoC state variables (T+1 states for T slots)
        min_soc_kwh = config.capacity_kwh * config.min_soc_percent / 100.0
        max_soc_kwh = config.capacity_kwh * config.max_soc_percent / 100.0

        soc = pulp.LpVariable.dicts(
            "soc_kwh", range(T + 1), lowBound=0.0, upBound=config.capacity_kwh
        )

        # Slack variables
        soc_violation = pulp.LpVariable.dicts("soc_violation_kwh", range(T + 1), lowBound=0.0)
        target_under_violation = pulp.LpVariable(
            "target_under_violation_kwh", lowBound=0.0
        )  # Penalty for being BELOW target at end of horizon
        target_over_violation = pulp.LpVariable(
            "target_over_violation_kwh", lowBound=0.0
        )  # Penalty for being ABOVE target at end of horizon
        import_breach = pulp.LpVariable.dicts("import_breach_kwh", range(T), lowBound=0.0)
        ramp_up = pulp.LpVariable.dicts("ramp_up_kwh", range(T), lowBound=0.0)
        ramp_down = pulp.LpVariable.dicts("ramp_down_kwh", range(T), lowBound=0.0)

        # Initial SoC Constraint
        initial_soc = max(0.0, min(config.capacity_kwh, input_data.initial_soc_kwh))
        prob += soc[0] == initial_soc

        # Objective Function Terms
        total_cost = []

        # Penalty constants
        MIN_SOC_PENALTY = 1000.0  # Hard constraint - don't violate min_soc!
        # Target penalty comes from config (derived from risk_appetite in pipeline)
        target_soc_penalty = config.target_soc_penalty_sek
        CURTAILMENT_PENALTY = 0.1
        LOAD_SHEDDING_PENALTY = 10000.0
        IMPORT_BREACH_PENALTY = 5000.0

        for t in range(T):
            s = slots[t]
            h = slot_hours[t]

            # Water heating load for this slot (kWh)
            water_load_kwh = (
                water_heat[t] * config.water_heating_power_kw * h if water_enabled else 0
            )

            # Energy Balance Constraint (water load added to demand side)
            prob += (
                s.load_kwh + water_load_kwh + charge[t] + grid_export[t] + curtailment[t]
                == s.pv_kwh + discharge[t] + grid_import[t] + load_shedding[t]
            )

            # Rev K21: Water start detection
            if water_enabled:
                if t == 0:
                    prob += water_start[t] == water_heat[t]
                else:
                    prob += water_start[t] >= water_heat[t] - water_heat[t - 1]

            # Rev WH2: Force specific slots ON (Mid-block locking)
            if water_enabled and config.force_water_on_slots:
                for t_idx in config.force_water_on_slots:
                    if 0 <= t_idx < T:
                        prob += water_heat[t_idx] == 1

            # Battery Dynamics Constraint
            prob += soc[t + 1] == soc[t] + charge[t] * config.charge_efficiency - discharge[t] / (
                config.discharge_efficiency if config.discharge_efficiency > 0 else 1.0
            )

            # Power Limits
            max_chg_kwh = config.max_charge_power_kw * h
            max_dis_kwh = config.max_discharge_power_kw * h

            prob += charge[t] <= max_chg_kwh
            prob += discharge[t] <= max_dis_kwh

            if config.max_export_power_kw is not None:
                prob += grid_export[t] <= config.max_export_power_kw * h

            if config.max_import_power_kw is not None:
                prob += grid_import[t] <= config.max_import_power_kw * h

            # Soft Grid Import Limit
            if config.grid_import_limit_kw is not None:
                limit_kwh = config.grid_import_limit_kw * h
                prob += grid_import[t] <= limit_kwh + import_breach[t]

            # Ramping Constraints
            if t > 0:
                prob += (charge[t] - discharge[t]) - (charge[t - 1] - discharge[t - 1]) == ramp_up[
                    t
                ] - ramp_down[t]
            else:
                prob += ramp_up[t] == 0
                prob += ramp_down[t] == 0

            # Objective Terms
            slot_wear_cost = (charge[t] + discharge[t]) * config.wear_cost_sek_per_kwh
            slot_import_cost = grid_import[t] * s.import_price_sek_kwh
            effective_export_price = s.export_price_sek_kwh - config.export_threshold_sek_per_kwh
            slot_export_revenue = grid_export[t] * effective_export_price
            slot_ramping_cost = ((ramp_up[t] + ramp_down[t]) / h) * config.ramping_cost_sek_per_kw
            slot_curtailment_cost = curtailment[t] * CURTAILMENT_PENALTY
            slot_shedding_cost = load_shedding[t] * LOAD_SHEDDING_PENALTY
            slot_import_breach_cost = import_breach[t] * IMPORT_BREACH_PENALTY

            # NOTE: Rev K20 stored_energy_cost was removed - it incorrectly made
            # charging unprofitable by adding cost on discharge without offsetting
            # credit on charge. The terminal_value and wear_cost are sufficient
            # for arbitrage decisions.

            total_cost.append(
                slot_import_cost
                - slot_export_revenue
                + slot_wear_cost
                + slot_ramping_cost
                + slot_curtailment_cost
                + slot_shedding_cost
                + slot_import_breach_cost
            )

            # Soft Min/Max SoC Constraints
            prob += soc[t] >= min_soc_kwh - soc_violation[t]
            prob += soc[t] <= max_soc_kwh

        # Terminal constraints
        prob += soc[T] >= min_soc_kwh - soc_violation[T]
        prob += soc[T] <= max_soc_kwh

        # Terminal SoC Target (BIDIRECTIONAL soft constraint)
        # Penalize both being UNDER target (risk) AND OVER target (missed discharge opportunity)
        target_soc_kwh = config.target_soc_kwh if config.target_soc_kwh is not None else min_soc_kwh
        if config.target_soc_kwh is not None:
            # Under target: soc[T] >= target - under_violation
            prob += soc[T] >= target_soc_kwh - target_under_violation
            # Over target: soc[T] <= target + over_violation
            prob += soc[T] <= target_soc_kwh + target_over_violation

        # Water Heating Constraints (Rev K17/K18/K21)
        gap_violation_penalty = 0.0
        spacing_violation_penalty = 0.0
        if water_enabled:
            avg_slot_hours = sum(slot_hours) / len(slot_hours) if slot_hours else 0.25
            water_kwh_per_slot = config.water_heating_power_kw * avg_slot_hours

            # Constraint 1: Per-day min_kwh requirements
            # Group slots by date to apply daily minimum constraints
            # Rev WH2: Smart Deferral - extend buckets into next morning
            slots_by_day = defaultdict(list)
            defer_hours = config.defer_up_to_hours
            
            for t in range(T):
                dt = slots[t].start_time
                bucket_date = dt.date()
                if defer_hours > 0 and dt.hour < defer_hours:
                    bucket_date = bucket_date - timedelta(days=1)

                slots_by_day[bucket_date].append(t)

            # Sort days to identify "today" (first day in horizon)
            sorted_days = sorted(slots_by_day.keys())

            for i, day in enumerate(sorted_days):
                day_slot_indices = slots_by_day[day]
                if i == 0:
                    # First day: reduce by what's already heated today
                    day_min_kwh = max(
                        0.0, config.water_heating_min_kwh - config.water_heated_today_kwh
                    )
                else:
                    # Future days: full daily requirement
                    day_min_kwh = config.water_heating_min_kwh

                if day_min_kwh > 0:
                    prob += (
                        pulp.lpSum(water_heat[t] for t in day_slot_indices) * water_kwh_per_slot
                        >= day_min_kwh
                    )

            # Constraint 2: Progressive gap penalty (Rev K18/K21)
            # Tier 1: Base comfort penalty beyond max_gap_hours
            if config.water_heating_max_gap_hours > 0 and config.water_comfort_penalty_sek > 0:
                gap_slots = max(1, int(config.water_heating_max_gap_hours / avg_slot_hours))
                gap_violation = pulp.LpVariable.dicts("gap_viol", range(T), lowBound=0.0)
                for start in range(T - gap_slots + 1):
                    prob += (
                        pulp.lpSum(water_heat[t] for t in range(start, start + gap_slots))
                        + gap_violation[start]
                        >= 1
                    )

                # Tier 2: Double penalty for very long gaps (> 1.5x threshold)
                gap_slots_2 = max(1, int(config.water_heating_max_gap_hours * 1.5 / avg_slot_hours))
                gap_violation_2 = pulp.LpVariable.dicts("gap_viol_2", range(T), lowBound=0.0)
                for start in range(T - gap_slots_2 + 1):
                    prob += (
                        pulp.lpSum(water_heat[t] for t in range(start, start + gap_slots_2))
                        + gap_violation_2[start]
                        >= 1
                    )

                gap_violation_penalty = config.water_comfort_penalty_sek * (
                    pulp.lpSum(gap_violation[t] for t in range(T - gap_slots + 1))
                    + pulp.lpSum(gap_violation_2[t] for t in range(T - gap_slots_2 + 1))
                )

            # Constraint 3: Soft Efficiency Penalty (Spacing) (Rev K21)
            # If a new block starts, it shouldn't be too close to any previous heating
            if config.water_min_spacing_hours > 0 and config.water_spacing_penalty_sek > 0:
                spacing_slots = max(1, int(config.water_min_spacing_hours / avg_slot_hours))
                for t in range(T):
                    # Check preceding slots in spacing window
                    for j in range(max(0, t - spacing_slots), t):
                        # If we start at t AND were heating at j, it's a spacing violation
                        # Linearized: viol >= start[t] + heat[j] - 1
                        prob += water_spacing_viol[t] >= water_start[t] + water_heat[j] - 1

                spacing_violation_penalty = config.water_spacing_penalty_sek * pulp.lpSum(
                    water_spacing_viol
                )

        # Terminal Value
        terminal_value = soc[T] * config.terminal_value_sek_kwh

        # Set Objective
        # - min_soc violation: HARD penalty (1000 SEK/kWh)
        # - target violation: SOFT penalty (from config, derived from risk_appetite)
        #   * UNDER target: Risk penalty (configurable)
        #   * OVER target: Opportunity cost penalty (same as under)
        # - gap violation: SOFT comfort penalty (Rev K18)
        prob += (
            pulp.lpSum(total_cost)
            - terminal_value
            + MIN_SOC_PENALTY * pulp.lpSum(soc_violation)
            + target_soc_penalty * target_under_violation
            + target_soc_penalty * target_over_violation
            + gap_violation_penalty
            + spacing_violation_penalty
            + (
                pulp.lpSum(water_start[t] for t in range(T)) * config.water_block_start_penalty_sek
                if water_enabled and config.water_block_start_penalty_sek > 0
                else 0.0
            )  # Rev WH2: Block start penalty
        )

        # Solve using GLPK (available in Alpine) or CBC as fallback
        try:
            # Try GLPK first (installed in Alpine Docker image)
            prob.solve(pulp.GLPK_CMD(msg=False))
        except Exception:
            # Fall back to CBC if GLPK not available
            prob.solve(pulp.PULP_CBC_CMD(msg=False))

        # Extract Results
        status = pulp.LpStatus[prob.status]
        is_optimal = status == "Optimal"

        if not is_optimal:
            prob.writeLP("kepler_debug.lp")
            print(f"Solver failed: {status}. LP written to kepler_debug.lp")

        result_slots = []
        final_total_cost = 0.0

        if is_optimal:
            for t in range(T):
                s = slots[t]
                h = slot_hours[t]

                c_val = pulp.value(charge[t])
                d_val = pulp.value(discharge[t])
                i_val = pulp.value(grid_import[t])
                e_val = pulp.value(grid_export[t])
                soc_val = pulp.value(soc[t + 1])

                # Water heating power (kW) from binary decision
                if water_enabled:
                    w_val = pulp.value(water_heat[t])
                    w_kw = config.water_heating_power_kw if w_val and w_val > 0.5 else 0.0
                else:
                    w_kw = 0.0

                wear = (c_val + d_val) * config.wear_cost_sek_per_kwh
                cost = (i_val * s.import_price_sek_kwh) - (e_val * s.export_price_sek_kwh) + wear
                final_total_cost += cost

                result_slots.append(
                    KeplerResultSlot(
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
                        water_heat_kw=w_kw,
                        is_optimal=True,
                    )
                )

        return KeplerResult(
            slots=result_slots,
            total_cost_sek=final_total_cost,
            is_optimal=is_optimal,
            status_msg=status,
        )
