import json
import math

import pandas as pd
import yaml

from inputs import get_all_input_data

class HeliosPlanner:
    def __init__(self, config_path):
        """
        Initialize the HeliosPlanner with configuration from YAML file.
        
        Args:
            config_path (str): Path to the configuration YAML file
        """
        # Load config from YAML
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

        # Initialize internal state
        self.timezone = self.config.get('timezone', 'Europe/Stockholm')
        self.battery_config = self.config.get('system', {}).get('battery', self.config.get('battery', {}))
        if not self.battery_config:
            self.battery_config = self.config.get('battery', {})
        self.thresholds = self.config.get('decision_thresholds', {})
        self.charging_strategy = self.config.get('charging_strategy', {})
        self.strategic_charging = self.config.get('strategic_charging', {})
        self.water_heating_config = self.config.get('water_heating', {})
        self.safety_config = self.config.get('safety', {})
        self.battery_economics = self.config.get('battery_economics', {})

        roundtrip_percent = self.battery_config.get(
            'roundtrip_efficiency_percent',
            self.battery_config.get('efficiency_percent', 95.0),
        )
        self.roundtrip_efficiency = max(0.0, min(roundtrip_percent / 100.0, 1.0))
        if self.roundtrip_efficiency > 0:
            efficiency_component = math.sqrt(self.roundtrip_efficiency)
            self.charge_efficiency = efficiency_component
            self.discharge_efficiency = efficiency_component
        else:
            self.charge_efficiency = 0.0
            self.discharge_efficiency = 0.0

        self.cycle_cost = self.battery_economics.get('battery_cycle_cost_kwh', 0.0)

    def _energy_into_battery(self, source_energy_kwh: float) -> float:
        """Energy (kWh) stored in the battery after charging losses."""
        return source_energy_kwh * self.charge_efficiency

    def _battery_energy_for_output(self, required_output_kwh: float) -> float:
        """Energy (kWh) that must be removed from the battery to deliver output after losses."""
        if self.discharge_efficiency == 0:
            return float('inf')
        return required_output_kwh / self.discharge_efficiency

    def _battery_output_from_energy(self, battery_energy_kwh: float) -> float:
        """Energy (kWh) delivered after accounting for discharge losses."""
        return battery_energy_kwh * self.discharge_efficiency

    def _available_charge_power_kw(self, row) -> float:
        """
        Compute realistic available charge power for a slot respecting inverter, grid, water heating, and net load.
        Returns 0 if constraints prevent charging.
        """
        inverter_max = self.config.get('system', {}).get('inverter', {}).get('max_power_kw', 10.0)
        grid_max = self.config.get('system', {}).get('grid', {}).get('max_power_kw', 25.0)
        battery_max = self.battery_config.get('max_charge_power_kw', 5.0)

        water_kw = row.get('water_heating_kw', 0.0)
        net_load_kw = max(0.0, (row.get('adjusted_load_kwh', 0.0) - row.get('adjusted_pv_kwh', 0.0)) / 0.25)

        available = min(inverter_max, grid_max, battery_max) - water_kw - net_load_kw
        return max(0.0, available)

    def generate_schedule(self, input_data):
        """
        The main method that executes all planning passes and returns the schedule.

        Args:
            input_data (dict): Dictionary containing nordpool data, forecast data, and initial state

        Returns:
            pd.DataFrame: Prepared DataFrame for now
        """
        df = self._prepare_data_frame(input_data)
        self.state = input_data['initial_state']
        df = self._pass_0_apply_safety_margins(df)
        df = self._pass_1_identify_windows(df)
        df = self._pass_2_schedule_water_heating(df)
        df = self._pass_3_simulate_baseline_depletion(df)
        df = self._pass_4_allocate_cascading_responsibilities(df)
        df = self._pass_5_distribute_charging_in_windows(df)
        df = self._pass_6_finalize_schedule(df)
        df = self._pass_7_enforce_hysteresis(df)
        self._save_schedule_to_json(df)
        return df

    def _prepare_data_frame(self, input_data):
        """
        Create a timezone-aware pandas DataFrame indexed by time for the planning horizon.

        Columns: import_price, export_price, pv_forecast_kwh, load_forecast_kwh, etc.

        Args:
            input_data (dict): Input data containing market prices, forecasts, and initial state

        Returns:
            pd.DataFrame: Prepared DataFrame with all necessary columns for planning
        """
        price_data = input_data['price_data']
        forecast_data = input_data['forecast_data']

        # Combine into DataFrame
        df = pd.DataFrame({
            'start_time': [slot['start_time'] for slot in price_data],
            'end_time': [slot['end_time'] for slot in price_data],
            'import_price_sek_kwh': [slot['import_price_sek_kwh'] for slot in price_data],
            'export_price_sek_kwh': [slot['export_price_sek_kwh'] for slot in price_data],
            'pv_forecast_kwh': [f['pv_forecast_kwh'] for f in forecast_data],
            'load_forecast_kwh': [f['load_forecast_kwh'] for f in forecast_data]
        })

        # Set index to start_time
        df.set_index('start_time', inplace=True)
        return df

    def _pass_0_apply_safety_margins(self, df):
        """
        Apply safety margins to PV and load forecasts.

        Args:
            df (pd.DataFrame): DataFrame with forecasts

        Returns:
            pd.DataFrame: DataFrame with adjusted forecasts
        """
        forecasting = self.config.get('forecasting', {})
        pv_confidence = forecasting.get('pv_confidence_percent', 90.0) / 100.0
        load_margin = forecasting.get('load_safety_margin_percent', 110.0) / 100.0
        df['adjusted_pv_kwh'] = df['pv_forecast_kwh'] * pv_confidence
        df['adjusted_load_kwh'] = df['load_forecast_kwh'] * load_margin
        return df

    def _pass_1_identify_windows(self, df):
        """
        Calculate price percentiles and apply cheap_price_tolerance_sek.
        Identify and group consecutive cheap slots into charging 'windows'.
        Detect if a strategic period is active (PV forecast < Load forecast).

        Args:
            df (pd.DataFrame): DataFrame with prepared data

        Returns:
            pd.DataFrame: DataFrame with is_cheap column and strategic period set
        """
        # Calculate price threshold using two-step logic with smoothing
        charge_threshold_percentile = self.charging_strategy.get('charge_threshold_percentile', 15)
        cheap_price_tolerance_sek = self.charging_strategy.get('cheap_price_tolerance_sek', 0.10)
        price_smoothing_sek_kwh = self.config.get('smoothing', {}).get('price_smoothing_sek_kwh', 0.05)

        # Step A: Initial cheap slots below percentile
        initial_cheap = df['import_price_sek_kwh'] <= df['import_price_sek_kwh'].quantile(charge_threshold_percentile / 100.0)

        # Step B: Maximum price among initial cheap slots
        max_price_in_initial = df.loc[initial_cheap, 'import_price_sek_kwh'].max()

        # Step C: Final threshold with smoothing tolerance
        cheap_price_threshold = max_price_in_initial + cheap_price_tolerance_sek + price_smoothing_sek_kwh

        # Step D: Final is_cheap with smoothing
        df['is_cheap'] = df['import_price_sek_kwh'] <= cheap_price_threshold

        # Detect strategic period
        total_pv = df['adjusted_pv_kwh'].sum()
        total_load = df['adjusted_load_kwh'].sum()
        self.is_strategic_period = total_pv < total_load

        return df

    def _pass_2_schedule_water_heating(self, df):
        """
        Schedule water heating in contiguous blocks with preference for single block.

        Args:
            df (pd.DataFrame): DataFrame with prepared data

        Returns:
            pd.DataFrame: Updated DataFrame with water heating schedule
        """
        from datetime import timedelta

        # Get configuration
        power_kw = self.water_heating_config.get('power_kw', 3.0)
        min_hours_per_day = self.water_heating_config.get('min_hours_per_day', 2.0)
        min_kwh_per_day = self.water_heating_config.get('min_kwh_per_day', power_kw * min_hours_per_day)
        max_blocks_per_day = self.water_heating_config.get('max_blocks_per_day', 2)
        schedule_future_only = self.water_heating_config.get('schedule_future_only', True)

        # Calculate required slots per block
        slot_energy_kwh = power_kw * 0.25  # 15-minute slots
        slots_per_block = max(1, int(min_kwh_per_day / slot_energy_kwh))

        # Get today's water usage (placeholder - will integrate with HA/sqlite later)
        daily_water_kwh_today = 0.5  # hardcoded for now

        # Determine if we need to schedule for today or tomorrow
        first_start = df.index[0]
        is_today_complete = daily_water_kwh_today >= min_kwh_per_day

        if schedule_future_only:
            # Only schedule future slots
            available_slots = df[df.index > first_start]
        else:
            available_slots = df

        if is_today_complete:
            # Schedule for tomorrow
            tomorrow = first_start.date() + timedelta(days=1)
            available_slots = available_slots[available_slots.index.date == tomorrow]

        # Find contiguous blocks of cheap slots
        cheap_slots = available_slots[available_slots['is_cheap']].copy()
        blocks = []
        selected_blocks = []

        if not cheap_slots.empty:
            # Group into contiguous blocks
            current_block = {'start': cheap_slots.index[0], 'length': 1}
            for i in range(1, len(cheap_slots)):
                current_time = cheap_slots.index[i]
                prev_time = cheap_slots.index[i-1]
                if (current_time - prev_time).total_seconds() == 900:  # 15 minutes
                    current_block['length'] += 1
                else:
                    blocks.append(current_block)
                    current_block = {'start': current_time, 'length': 1}
            blocks.append(current_block)

            # Filter blocks that are large enough and sort by average price
            valid_blocks = [b for b in blocks if b['length'] >= slots_per_block]
            valid_blocks.sort(key=lambda b: available_slots.loc[b['start']:available_slots.index[available_slots.index.get_loc(b['start']) + b['length'] - 1], 'import_price_sek_kwh'].mean())

            # Select blocks (prefer single block, allow up to max_blocks_per_day)
            selected_blocks = []
            remaining_energy = min_kwh_per_day

            for block in valid_blocks:
                if len(selected_blocks) >= max_blocks_per_day:
                    break
                block_energy = min(block['length'] * slot_energy_kwh, remaining_energy)
                if block_energy > 0:
                    selected_blocks.append({
                        'start': block['start'],
                        'slots_needed': min(block['length'], int(block_energy / slot_energy_kwh))
                    })
                    remaining_energy -= block_energy
                    if remaining_energy <= 0:
                        break

        # Apply scheduling to DataFrame
        df['water_heating_kw'] = 0.0
        for block in selected_blocks:
            start_idx = block['start']
            slots_needed = block['slots_needed']
            for i in range(slots_needed):
                slot_time = start_idx + timedelta(minutes=i * 15)
                if slot_time in df.index:
                    df.loc[slot_time, 'water_heating_kw'] = power_kw

        return df
        
    def _pass_3_simulate_baseline_depletion(self, df):
        """
        Simulate battery SoC evolution with economic decisions for discharging.
        Stores window start states for later gap calculations.

        Args:
            df (pd.DataFrame): DataFrame with water heating scheduled

        Returns:
            pd.DataFrame: DataFrame with baseline SoC projections and window start states
        """
        capacity_kwh = self.battery_config.get('capacity_kwh', 10.0)
        min_soc_percent = self.battery_config.get('min_soc_percent', 15)
        max_soc_percent = self.battery_config.get('max_soc_percent', 95)

        min_soc_kwh = min_soc_percent / 100.0 * capacity_kwh
        max_soc_kwh = max_soc_percent / 100.0 * capacity_kwh
        battery_use_margin_sek = self.thresholds.get('battery_use_margin_sek', 0.10)
        battery_cost = self.state['battery_cost_sek_per_kwh']
        economic_threshold = battery_cost + self.cycle_cost + battery_use_margin_sek

        current_kwh = self.state['battery_kwh']
        soc_list = []
        window_start_states = []

        for idx, row in df.iterrows():
            # Record window start state
            if row.get('is_cheap', False):
                window_start_states.append({
                    'start': idx,
                    'soc_kwh': current_kwh,
                    'avg_cost_sek_per_kwh': battery_cost,
                })

            adjusted_pv = row['adjusted_pv_kwh']
            adjusted_load = row['adjusted_load_kwh']
            water_kwh = row['water_heating_kw'] * 0.25
            import_price = row['import_price_sek_kwh']

            # Case 1: Deficit
            deficit_kwh = adjusted_load + water_kwh - adjusted_pv
            if (
                deficit_kwh > 0
                and import_price > economic_threshold
                and self.discharge_efficiency > 0
            ):
                discharge_from_battery = self._battery_energy_for_output(deficit_kwh)
                current_kwh -= discharge_from_battery

            # Case 2: Surplus
            surplus_kwh = adjusted_pv - adjusted_load - water_kwh
            if surplus_kwh > 0 and self.charge_efficiency > 0:
                charge_to_battery = self._energy_into_battery(surplus_kwh)
                current_kwh += charge_to_battery

            # Clamp
            current_kwh = max(min_soc_kwh, min(max_soc_kwh, current_kwh))
            soc_list.append(current_kwh)

        df['simulated_soc_kwh'] = soc_list
        self.window_start_states = window_start_states
        return df

    def _pass_4_allocate_cascading_responsibilities(self, df):
        """
        Advanced MPC logic with price-aware gap energy, S-index safety, and strategic carry-forward.

        Args:
            df (pd.DataFrame): DataFrame with baseline projections and window start states

        Returns:
            pd.DataFrame: Original DataFrame (responsibilities stored in instance attribute)
        """
        # Group slots into windows
        windows = []
        current_window = None
        for idx, row in df.iterrows():
            if row['is_cheap']:
                if current_window is None:
                    current_window = {'start': idx, 'end': idx}
                else:
                    current_window['end'] = idx
            else:
                if current_window is not None:
                    windows.append(current_window)
                    current_window = None
        if current_window is not None:
            windows.append(current_window)

        # Identify strategic windows
        strategic_windows = []
        strategic_price_threshold_sek = self.strategic_charging.get('price_threshold_sek', 0.90)
        for i, window in enumerate(windows):
            start_idx = window['start']
            end_idx = window['end']
            window_prices = df.loc[start_idx:end_idx, 'import_price_sek_kwh']
            if self.is_strategic_period and (window_prices < strategic_price_threshold_sek).any():
                strategic_windows.append(i)

        # S-index factor
        s_index_cfg = self.config.get('s_index', {})
        s_index_mode = s_index_cfg.get('mode', 'static')
        s_index_factor = s_index_cfg.get('static_factor', 1.05)
        s_index_max = s_index_cfg.get('max_factor', 1.25)
        s_index_factor = min(s_index_factor, s_index_max)

        # Calculate price-aware gap responsibilities
        self.window_responsibilities = []
        capacity_kwh = self.battery_config.get('capacity_kwh', 10.0)
        min_soc_percent = self.battery_config.get('min_soc_percent', 15)
        max_soc_percent = self.battery_config.get('max_soc_percent', 95)

        min_soc_kwh = min_soc_percent / 100.0 * capacity_kwh
        max_soc_kwh = max_soc_percent / 100.0 * capacity_kwh
        max_charge_power_kw = self.battery_config.get('max_charge_power_kw', 5.0)

        for i, window in enumerate(windows):
            start_idx = window['start']
            end_idx = window['end']
            window_df = df.loc[start_idx:end_idx]

            # Find the window start state (SoC and avg cost)
            start_state = next((s for s in getattr(self, 'window_start_states', []) if s['start'] == start_idx), None)
            soc_at_window_start = start_state['soc_kwh'] if start_state else df.loc[start_idx, 'simulated_soc_kwh']
            avg_cost_at_start = start_state['avg_cost_sek_per_kwh'] if start_state else self.state.get('battery_cost_sek_per_kwh', 0.0)

            # Compute gap energy only for slots where battery would be economical
            economic_threshold = avg_cost_at_start + self.cycle_cost + self.thresholds.get('battery_use_margin_sek', 0.10)
            gap_slots = window_df[window_df['import_price_sek_kwh'] > economic_threshold]
            gap_energy_kwh = gap_slots['adjusted_load_kwh'].sum() - gap_slots['adjusted_pv_kwh'].sum()
            gap_energy_kwh = max(0.0, gap_energy_kwh)

            # Apply S-index safety factor
            total_responsibility_kwh = gap_energy_kwh * s_index_factor

            self.window_responsibilities.append({
                'window': window,
                'total_responsibility_kwh': total_responsibility_kwh,
                'start_soc_kwh': soc_at_window_start,
                'start_avg_cost_sek_per_kwh': avg_cost_at_start,
            })

        # Strategic override to absolute target
        strategic_target_soc_percent = self.battery_config.get('max_soc_percent', 95)
        strategic_target_kwh = strategic_target_soc_percent / 100.0 * capacity_kwh
        for i in strategic_windows:
            start_idx = windows[i]['start']
            soc_at_window_start = df.loc[start_idx, 'simulated_soc_kwh']
            self.window_responsibilities[i]['total_responsibility_kwh'] = max(
                0, strategic_target_kwh - soc_at_window_start
            )

        # Cascading with realistic capacity and self-depletion
        for i in range(len(windows) - 2, -1, -1):
            next_i = i + 1
            next_resp = self.window_responsibilities[next_i]['total_responsibility_kwh']
            next_window = windows[next_i]
            next_df = df.loc[next_window['start']:next_window['end']]

            # Compute realistic charge capacity for the next window
            realistic_charge_kw = max(0.0, max_charge_power_kw - next_df['water_heating_kw'].mean() - (next_df['adjusted_load_kwh'].mean() / 0.25))
            num_slots = len(next_df)
            max_energy = realistic_charge_kw * num_slots * 0.25 * self.charge_efficiency

            # Add self-depletion during the next window to its responsibility
            net_load_next = (next_df['adjusted_load_kwh'] - next_df['adjusted_pv_kwh']).sum()
            self_depletion_kwh = max(0.0, net_load_next)
            adjusted_next_resp = next_resp + self_depletion_kwh

            if adjusted_next_resp > max_energy:
                self.window_responsibilities[i]['total_responsibility_kwh'] += adjusted_next_resp

        # Strategic carry-forward
        carry_tolerance = self.strategic_charging.get('carry_forward_tolerance_ratio', 0.10)
        for i in strategic_windows:
            window = windows[i]
            start_idx = window['start']
            soc_at_window_start = df.loc[start_idx, 'simulated_soc_kwh']
            resp = self.window_responsibilities[i]['total_responsibility_kwh']
            soc_after = soc_at_window_start + resp * self.charge_efficiency
            if soc_after < strategic_target_kwh and i + 1 < len(windows):
                remaining_energy = strategic_target_kwh - soc_after
                next_window = windows[i + 1]
                next_window_prices = df.loc[next_window['start']:next_window['end'], 'import_price_sek_kwh']
                if (next_window_prices <= strategic_price_threshold_sek * (1 + carry_tolerance)).any():
                    self.window_responsibilities[i + 1]['total_responsibility_kwh'] += remaining_energy / self.charge_efficiency

        return df

    def _pass_5_distribute_charging_in_windows(self, df):
        """
        For each window, sort slots by price.
        Iteratively assign 'Charge' action to the cheapest slots until the window's
        total charging responsibility (in kWh) is met, respecting realistic power limits.

        Args:
            df (pd.DataFrame): DataFrame with allocated responsibilities

        Returns:
            pd.DataFrame: DataFrame with detailed charging assignments
        """
        df['charge_kw'] = 0.0
        max_charge_power_kw = self.battery_config.get('max_charge_power_kw', 5.0)

        for resp in self.window_responsibilities:
            window = resp['window']
            total_responsibility_kwh = resp['total_responsibility_kwh']
            window_df = df.loc[window['start']:window['end']].sort_values('import_price_sek_kwh')

            for idx, row in window_df.iterrows():
                if total_responsibility_kwh > 0:
                    available_kw = self._available_charge_power_kw(row)
                    charge_kw_for_slot = min(available_kw, max_charge_power_kw)
                    charge_kwh_for_slot = charge_kw_for_slot * 0.25
                    df.loc[idx, 'charge_kw'] = charge_kw_for_slot
                    total_responsibility_kwh -= charge_kwh_for_slot

        return df

    def _pass_6_finalize_schedule(self, df):
        """
        Generate the final schedule with rule-based decision hierarchy and MPC principles.

        Args:
            df (pd.DataFrame): DataFrame with charging assignments

        Returns:
            pd.DataFrame: DataFrame with final schedule
        """
        current_kwh = self.state['battery_kwh']
        starting_avg_cost = self.state.get('battery_cost_sek_per_kwh', 0.0)
        total_cost = current_kwh * starting_avg_cost

        capacity_kwh = self.battery_config.get('capacity_kwh', 10.0)
        min_soc_percent = self.battery_config.get('min_soc_percent', 15)
        max_soc_percent = self.battery_config.get('max_soc_percent', 95)

        min_soc_kwh = min_soc_percent / 100.0 * capacity_kwh
        max_soc_kwh = max_soc_percent / 100.0 * capacity_kwh
        battery_use_margin_sek = self.thresholds.get('battery_use_margin_sek', 0.10)

        actions = []
        projected_soc_kwh = []
        projected_soc_percent = []
        projected_battery_cost = []
        water_from_pv = []
        water_from_battery = []
        water_from_grid = []
        export_kwh = []
        export_revenue = []

        # Calculate protective SoC for export
        arbitrage_config = self.config.get('arbitrage', {})
        enable_export = arbitrage_config.get('enable_export', True)
        protective_soc_strategy = arbitrage_config.get('protective_soc_strategy', 'gap_based')
        fixed_protective_soc_percent = arbitrage_config.get('fixed_protective_soc_percent', 15.0)

        if protective_soc_strategy == 'gap_based':
            # Calculate protective SoC based on future responsibilities
            future_responsibilities = sum(resp['total_responsibility_kwh'] for resp in getattr(self, 'window_responsibilities', []))
            protective_soc_kwh = max(min_soc_kwh, future_responsibilities * 1.1)  # 10% buffer
        else:
            protective_soc_kwh = fixed_protective_soc_percent / 100.0 * capacity_kwh

        for idx, row in df.iterrows():
            pv_kwh = row['adjusted_pv_kwh']
            load_kwh = row['adjusted_load_kwh']
            water_kwh_required = row['water_heating_kw'] * 0.25
            charge_kw = row['charge_kw']
            import_price = row['import_price_sek_kwh']
            export_price = row['export_price_sek_kwh']
            is_cheap = row['is_cheap']

            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
            cycle_adjusted_cost = avg_cost + self.cycle_cost

            action = 'Hold'
            slot_export_kwh = 0.0
            slot_export_revenue = 0.0

            # Water heating source selection: PV surplus → battery (economical) → grid
            water_from_pv_kwh = 0.0
            water_from_battery_kwh = 0.0
            water_from_grid_kwh = 0.0

            if water_kwh_required > 0:
                # Step 1: Use PV surplus first
                pv_surplus = max(0.0, pv_kwh - load_kwh)
                water_from_pv_kwh = min(water_kwh_required, pv_surplus)
                remaining_water = water_kwh_required - water_from_pv_kwh

                # Step 2: Use battery if economical
                if remaining_water > 0 and self.discharge_efficiency > 0:
                    battery_water_threshold = avg_cost + self.cycle_cost + self.thresholds.get('battery_water_margin_sek', 0.20)
                    if import_price > battery_water_threshold:
                        max_battery_output = self._battery_output_from_energy(max(0.0, current_kwh - min_soc_kwh))
                        battery_available = min(remaining_water, max_battery_output)
                        if battery_available > 0:
                            water_from_battery_kwh = battery_available
                            battery_energy_used = self._battery_energy_for_output(battery_available)
                            total_cost -= avg_cost * battery_energy_used
                            total_cost = max(0.0, total_cost)
                            current_kwh -= battery_energy_used
                            remaining_water -= battery_available

                # Step 3: Use grid for remaining
                water_from_grid_kwh = remaining_water

            # Calculate net after water heating sources
            net_kwh = pv_kwh - load_kwh - water_from_pv_kwh - water_from_battery_kwh - water_from_grid_kwh

            if charge_kw > 0 and self.charge_efficiency > 0:
                grid_energy = charge_kw * 0.25
                stored_energy = self._energy_into_battery(grid_energy)
                available_capacity = max(0.0, max_soc_kwh - current_kwh)
                if stored_energy > available_capacity and self.charge_efficiency > 0:
                    stored_energy = available_capacity
                    grid_energy = stored_energy / self.charge_efficiency if self.charge_efficiency > 0 else 0.0
                if stored_energy > 0:
                    current_kwh += stored_energy
                    total_cost += grid_energy * import_price
                    action = 'Charge'
            else:
                if net_kwh < 0:
                    if not is_cheap and self.discharge_efficiency > 0:
                        discharge_price_threshold = cycle_adjusted_cost + battery_use_margin_sek
                        if import_price > discharge_price_threshold:
                            deficit_kwh = -net_kwh
                            max_battery_output = self._battery_output_from_energy(max(0.0, current_kwh - min_soc_kwh))
                            deliverable_kwh = min(deficit_kwh, max_battery_output)
                            if deliverable_kwh > 0:
                                battery_energy_used = self._battery_energy_for_output(deliverable_kwh)
                                total_cost -= avg_cost * battery_energy_used
                                total_cost = max(0.0, total_cost)
                                current_kwh -= battery_energy_used
                                action = 'Discharge'
                elif net_kwh > 0 and self.charge_efficiency > 0:
                    stored_energy = self._energy_into_battery(net_kwh)
                    available_capacity = max(0.0, max_soc_kwh - current_kwh)
                    stored_energy = min(stored_energy, available_capacity)
                    if stored_energy > 0:
                        current_kwh += stored_energy
                        action = 'PV Charge'

            # Export logic: Check for profitable export when safe
            if enable_export and net_kwh > 0 and current_kwh > protective_soc_kwh:
                export_fees = arbitrage_config.get('export_fees_sek_per_kwh', 0.0)
                export_profit_margin = arbitrage_config.get('export_profit_margin_sek', 0.05)
                net_export_price = export_price - export_fees

                # Only export if profitable (export price > import price + margin)
                if net_export_price > import_price + export_profit_margin:
                    # Calculate how much we can export (limited by available energy above protective SoC)
                    available_for_export = current_kwh - protective_soc_kwh
                    max_export_kwh = min(net_kwh, available_for_export)

                    if max_export_kwh > 0:
                        slot_export_kwh = max_export_kwh
                        slot_export_revenue = slot_export_kwh * net_export_price
                        current_kwh -= slot_export_kwh
                        total_cost -= avg_cost * slot_export_kwh  # Reduce cost basis
                        total_cost = max(0.0, total_cost)
                        action = 'Export'

            current_kwh = max(min_soc_kwh, min(max_soc_kwh, current_kwh))
            if current_kwh <= 0:
                current_kwh = 0.0
                total_cost = 0.0

            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0

            actions.append(action)
            projected_soc_kwh.append(current_kwh)
            projected_soc_percent.append((current_kwh / capacity_kwh) * 100.0 if capacity_kwh else 0.0)
            projected_battery_cost.append(avg_cost)
            water_from_pv.append(water_from_pv_kwh)
            water_from_battery.append(water_from_battery_kwh)
            water_from_grid.append(water_from_grid_kwh)
            export_kwh.append(slot_export_kwh)
            export_revenue.append(slot_export_revenue)

        df['action'] = actions
        df['projected_soc_kwh'] = projected_soc_kwh
        df['projected_soc_percent'] = projected_soc_percent
        df['projected_battery_cost'] = projected_battery_cost
        df['water_from_pv_kwh'] = water_from_pv
        df['water_from_battery_kwh'] = water_from_battery
        df['water_from_grid_kwh'] = water_from_grid
        df['export_kwh'] = export_kwh
        df['export_revenue'] = export_revenue

        return df

    def _pass_7_enforce_hysteresis(self, df):
        """
        Apply hysteresis to enforce minimum action block lengths and eliminate single-slot toggles.

        Args:
            df (pd.DataFrame): DataFrame with finalized schedule

        Returns:
            pd.DataFrame: DataFrame with hysteresis applied
        """
        smoothing_config = self.config.get('smoothing', {})
        min_on_charge = smoothing_config.get('min_on_slots_charge', 2)
        min_off_charge = smoothing_config.get('min_off_slots_charge', 1)
        min_on_discharge = smoothing_config.get('min_on_slots_discharge', 2)
        min_off_discharge = smoothing_config.get('min_off_slots_discharge', 1)
        min_on_export = smoothing_config.get('min_on_slots_export', 2)

        actions = df['action'].tolist()
        n_slots = len(actions)

        # Apply hysteresis for each action type
        for i in range(n_slots):
            current_action = actions[i]

            # Handle Charge hysteresis
            if current_action == 'Charge':
                # Check if we have enough consecutive slots for minimum on time
                consecutive_count = 1
                for j in range(i + 1, min(i + min_on_charge, n_slots)):
                    if actions[j] == 'Charge':
                        consecutive_count += 1
                    else:
                        break

                # If we don't have minimum consecutive slots, check if we should extend or cancel
                if consecutive_count < min_on_charge:
                    # Look backwards for recent charge actions
                    recent_charge = False
                    for j in range(max(0, i - min_off_charge), i):
                        if actions[j] == 'Charge':
                            recent_charge = True
                            break

                    if recent_charge:
                        # Extend the previous charge block
                        actions[i] = 'Charge'
                    else:
                        # Cancel this single charge slot
                        actions[i] = 'Hold'

            # Handle Discharge hysteresis
            elif current_action == 'Discharge':
                consecutive_count = 1
                for j in range(i + 1, min(i + min_on_discharge, n_slots)):
                    if actions[j] == 'Discharge':
                        consecutive_count += 1
                    else:
                        break

                if consecutive_count < min_on_discharge:
                    recent_discharge = False
                    for j in range(max(0, i - min_off_discharge), i):
                        if actions[j] == 'Discharge':
                            recent_discharge = True
                            break

                    if recent_discharge:
                        actions[i] = 'Discharge'
                    else:
                        actions[i] = 'Hold'

            # Handle Export hysteresis
            elif current_action == 'Export':
                consecutive_count = 1
                for j in range(i + 1, min(i + min_on_export, n_slots)):
                    if actions[j] == 'Export':
                        consecutive_count += 1
                    else:
                        break

                if consecutive_count < min_on_export:
                    actions[i] = 'Hold'  # Cancel single export slots

        # Update the DataFrame with hysteresis-applied actions
        df['action'] = actions

        # Re-simulate the schedule with the new actions to update SoC and costs
        # This is a simplified approach - in production, we'd need to re-run the full simulation
        # For now, we'll just update the action classifications

        return df

    def _save_schedule_to_json(self, schedule_df):
        """
        Save the final schedule to schedule.json in the required format.

        Args:
            schedule_df (pd.DataFrame): The final schedule DataFrame
        """
        records = dataframe_to_json_response(schedule_df)

        output = {'schedule': records}

        # Add debug payload if enabled
        debug_config = self.config.get('debug', {})
        if debug_config.get('enable_planner_debug', False):
            debug_payload = self._generate_debug_payload(schedule_df)
            output['debug'] = debug_payload

        with open('schedule.json', 'w') as f:
            json.dump(output, f, indent=2)

    def _generate_debug_payload(self, schedule_df):
        """
        Generate debug payload with windows, gaps, charging plan, water analysis, and metrics.

        Args:
            schedule_df (pd.DataFrame): The final schedule DataFrame

        Returns:
            dict: Debug payload
        """
        debug_config = self.config.get('debug', {})
        sample_size = debug_config.get('sample_size', 30)

        # Sample the schedule for debug (first N slots)
        sample_df = schedule_df.head(sample_size)

        debug_payload = {
            'windows': self._prepare_windows_for_json(),
            'water_analysis': {
                'total_water_scheduled_kwh': round(schedule_df['water_heating_kw'].sum() * 0.25, 2),
                'water_from_pv_kwh': round(schedule_df['water_from_pv_kwh'].sum(), 2),
                'water_from_battery_kwh': round(schedule_df['water_from_battery_kwh'].sum(), 2),
                'water_from_grid_kwh': round(schedule_df['water_from_grid_kwh'].sum(), 2),
            },
            'charging_plan': {
                'total_charge_kwh': round(schedule_df['charge_kw'].sum() * 0.25, 2),
                'total_export_kwh': round(schedule_df['export_kwh'].sum(), 2),
                'total_export_revenue': round(schedule_df['export_revenue'].sum(), 2),
            },
            'metrics': {
                'total_pv_generation_kwh': round(schedule_df['adjusted_pv_kwh'].sum(), 2),
                'total_load_kwh': round(schedule_df['adjusted_load_kwh'].sum(), 2),
                'net_energy_balance_kwh': round(schedule_df['adjusted_pv_kwh'].sum() - schedule_df['adjusted_load_kwh'].sum(), 2),
                'final_soc_percent': round(schedule_df['projected_soc_percent'].iloc[-1], 2) if not schedule_df.empty else 0,
                'average_battery_cost': round(schedule_df['projected_battery_cost'].mean(), 2) if not schedule_df.empty else 0,
            },
            'sample_schedule': self._prepare_sample_schedule_for_json(sample_df),
        }

        return debug_payload

    def _prepare_sample_schedule_for_json(self, sample_df):
        """
        Prepare sample schedule DataFrame for JSON serialization.

        Args:
            sample_df (pd.DataFrame): Sample DataFrame

        Returns:
            list: List of records ready for JSON serialization
        """
        if sample_df.empty:
            return []

        # Reset index and convert to dict
        records = sample_df.reset_index().to_dict('records')

        # Convert timestamps to strings
        for record in records:
            for key, value in record.items():
                if hasattr(value, 'isoformat'):  # Timestamp objects
                    record[key] = value.isoformat()
                elif isinstance(value, float):
                    record[key] = round(value, 2)

        return records

    def _prepare_windows_for_json(self):
        """
        Prepare window responsibilities for JSON serialization.

        Returns:
            list: List of window dictionaries with timestamps converted to strings
        """
        windows = getattr(self, 'window_responsibilities', [])
        json_windows = []

        for window in windows:
            json_window = {}
            for key, value in window.items():
                if key == 'window':
                    # Handle nested window dict with timestamps
                    json_window[key] = {}
                    for w_key, w_value in value.items():
                        if hasattr(w_value, 'isoformat'):  # Timestamp
                            json_window[key][w_key] = w_value.isoformat()
                        else:
                            json_window[key][w_key] = w_value
                elif isinstance(value, float):
                    json_window[key] = round(value, 2)
                else:
                    json_window[key] = value
            json_windows.append(json_window)

        return json_windows


def dataframe_to_json_response(df):
    """
    Convert a DataFrame to the JSON response format required by the frontend.
    
    Args:
        df (pd.DataFrame): The schedule DataFrame
        
    Returns:
        list: List of dictionaries ready for JSON response
    """
    df_copy = df.reset_index().copy()
    df_copy.rename(columns={
        'action': 'classification',
        'charge_kw': 'battery_charge_kw'
    }, inplace=True)

    records = df_copy.to_dict('records')

    for i, record in enumerate(records):
        record['slot_number'] = i + 1
        record['start_time'] = record['start_time'].isoformat()
        record['end_time'] = record['end_time'].isoformat()

        # Make classification lowercase
        if 'classification' in record:
            record['classification'] = record['classification'].lower()

        # Add reason and priority fields (placeholder logic for now)
        classification = record.get('classification', 'hold')
        if classification == 'charge':
            record['reason'] = 'cheap_grid_power'
            record['priority'] = 'high'
        elif classification == 'discharge':
            record['reason'] = 'expensive_grid_power'
            record['priority'] = 'high'
        elif classification == 'pv charge':
            record['reason'] = 'excess_pv'
            record['priority'] = 'medium'
        elif classification == 'export':
            record['reason'] = 'profitable_export'
            record['priority'] = 'medium'
        else:
            record['reason'] = 'no_action_needed'
            record['priority'] = 'low'

        for key, value in record.items():
            if isinstance(value, float):
                record[key] = round(value, 2)

    return records


def simulate_schedule(df, config, initial_state):
    """
    Simulate a schedule with given battery actions and return the projected results.
    
    Args:
        df (pd.DataFrame): DataFrame with charge_kw and water_heating_kw set
        config (dict): Configuration dictionary
        initial_state (dict): Initial battery state
        
    Returns:
        pd.DataFrame: DataFrame with simulated projections
    """
    # Create a temporary planner instance to use its simulation logic
    temp_planner = HeliosPlanner.__new__(HeliosPlanner)
    temp_planner.config = config
    temp_planner.timezone = config.get('timezone', 'Europe/Stockholm')
    temp_planner.battery_config = config.get('system', {}).get('battery', config.get('battery', {}))
    temp_planner.thresholds = config.get('decision_thresholds', {})
    temp_planner.charging_strategy = config.get('charging_strategy', {})
    temp_planner.strategic_charging = config.get('strategic_charging', {})
    temp_planner.water_heating_config = config.get('water_heating', {})
    temp_planner.safety_config = config.get('safety', {})
    temp_planner.battery_economics = config.get('battery_economics', {})

    roundtrip_percent = temp_planner.battery_config.get(
        'roundtrip_efficiency_percent',
        temp_planner.battery_config.get('efficiency_percent', 95.0),
    )
    temp_planner.roundtrip_efficiency = max(0.0, min(roundtrip_percent / 100.0, 1.0))
    if temp_planner.roundtrip_efficiency > 0:
        efficiency_component = math.sqrt(temp_planner.roundtrip_efficiency)
        temp_planner.charge_efficiency = efficiency_component
        temp_planner.discharge_efficiency = efficiency_component
    else:
        temp_planner.charge_efficiency = 0.0
        temp_planner.discharge_efficiency = 0.0

    temp_planner.cycle_cost = temp_planner.battery_economics.get('battery_cycle_cost_kwh', 0.0)
    temp_planner.state = initial_state
    
    # Run the simulation pass
    return temp_planner._pass_6_finalize_schedule(df)


if __name__ == "__main__":
    input_data = get_all_input_data()
    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data)
    print("Successfully generated and saved schedule to schedule.json")