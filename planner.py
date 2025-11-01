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
        # Calculate price threshold using two-step logic
        charge_threshold_percentile = self.charging_strategy.get('charge_threshold_percentile', 15)
        cheap_price_tolerance_sek = self.charging_strategy.get('cheap_price_tolerance_sek', 0.10)

        # Step A: Initial cheap slots below percentile
        initial_cheap = df['import_price_sek_kwh'] <= df['import_price_sek_kwh'].quantile(charge_threshold_percentile / 100.0)

        # Step B: Maximum price among initial cheap slots
        max_price_in_initial = df.loc[initial_cheap, 'import_price_sek_kwh'].max()

        # Step C: Final threshold
        cheap_price_threshold = max_price_in_initial + cheap_price_tolerance_sek

        # Step D: Final is_cheap
        df['is_cheap'] = df['import_price_sek_kwh'] <= cheap_price_threshold

        # Detect strategic period
        total_pv = df['adjusted_pv_kwh'].sum()
        total_load = df['adjusted_load_kwh'].sum()
        self.is_strategic_period = total_pv < total_load

        return df

    def _pass_2_schedule_water_heating(self, df):
        """
        Schedule water heating with advanced future-day and dynamic source selection logic.

        Args:
            df (pd.DataFrame): DataFrame with prepared data

        Returns:
            pd.DataFrame: Updated DataFrame with water heating schedule
        """
        from datetime import timedelta

        # Get inputs
        daily_water_kwh_today = 0.5  # hardcoded
        power_kw = self.water_heating_config.get('power_kw', 3.0)
        daily_duration_hours = self.water_heating_config.get('daily_duration_hours', 2.0)
        water_minimum_kwh = power_kw * daily_duration_hours
        battery_water_margin_sek = self.thresholds.get('battery_water_margin_sek', 0.20)
        battery_cost = self.state['battery_cost_sek_per_kwh']

        # Future-day logic
        is_today_complete = daily_water_kwh_today >= water_minimum_kwh
        first_start = df.index[0]
        future_slots = df[df.index > first_start]

        if is_today_complete:
            tomorrow = first_start.date() + timedelta(days=1)
            future_slots = future_slots[future_slots.index.date == tomorrow]

        # Dynamic source selection
        candidates = []
        for idx, row in future_slots.iterrows():
            grid_cost = row['import_price_sek_kwh'] * (power_kw * 0.25)
            battery_cost_for_heating = battery_cost * (power_kw * 0.25)
            if row['import_price_sek_kwh'] > battery_cost + battery_water_margin_sek:
                cost = battery_cost_for_heating
            else:
                cost = grid_cost
            candidates.append({'index': idx, 'cost': cost})

        # Schedule heating
        candidates.sort(key=lambda x: x['cost'])
        num_slots = int(water_minimum_kwh / (power_kw * 0.25))
        selected = candidates[:num_slots]

        df['water_heating_kw'] = 0.0
        for cand in selected:
            df.loc[cand['index'], 'water_heating_kw'] = power_kw

        return df
        
    def _pass_3_simulate_baseline_depletion(self, df):
        """
        Simulate battery SoC evolution with economic decisions for discharging.

        Args:
            df (pd.DataFrame): DataFrame with water heating scheduled

        Returns:
            pd.DataFrame: DataFrame with baseline SoC projections
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

        for idx, row in df.iterrows():
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
        return df

    def _pass_4_allocate_cascading_responsibilities(self, df):
        """
        Advanced MPC logic with projected battery cost, realistic capacity estimation, and strategic carry-forward.

        Args:
            df (pd.DataFrame): DataFrame with baseline projections

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
        strategic_price_threshold_sek = self.strategic_charging['price_threshold_sek']
        for i, window in enumerate(windows):
            start_idx = window['start']
            end_idx = window['end']
            window_prices = df.loc[start_idx:end_idx, 'import_price_sek_kwh']
            if self.is_strategic_period and (window_prices < strategic_price_threshold_sek).any():
                strategic_windows.append(i)

        # Calculate basic responsibilities
        self.window_responsibilities = []
        capacity_kwh = self.battery_config.get('capacity_kwh', 10.0)
        min_soc_percent = self.battery_config.get('min_soc_percent', 15)
        max_soc_percent = self.battery_config.get('max_soc_percent', 95)
        efficiency_percent = self.battery_config.get('efficiency_percent', 95.0)
        
        min_soc_kwh = min_soc_percent / 100.0 * capacity_kwh
        max_soc_kwh = max_soc_percent / 100.0 * capacity_kwh
        efficiency = efficiency_percent / 100.0
        max_charge_power_kw = self.battery_config.get('max_charge_power_kw', 5.0)

        for i, window in enumerate(windows):
            start_idx = window['start']
            end_idx = window['end']
            soc_at_window_start = df.loc[start_idx, 'simulated_soc_kwh']

            if i + 1 < len(windows):
                next_window_start = windows[i + 1]['start']
                min_soc_until_next = df.loc[start_idx:next_window_start, 'simulated_soc_kwh'].min()
            else:
                min_soc_until_next = df.loc[start_idx:, 'simulated_soc_kwh'].min()

            energy_gap_kwh = min_soc_kwh - min_soc_until_next
            total_responsibility_kwh = max(0, energy_gap_kwh)

            self.window_responsibilities.append({
                'window': window,
                'total_responsibility_kwh': total_responsibility_kwh
            })

        # Strategic override
        strategic_target_soc_percent = self.strategic_charging['target_soc_percent']
        strategic_target_kwh = strategic_target_soc_percent / 100.0 * capacity_kwh
        for i in strategic_windows:
            window = windows[i]
            start_idx = window['start']
            soc_at_window_start = df.loc[start_idx, 'simulated_soc_kwh']
            self.window_responsibilities[i]['total_responsibility_kwh'] = max(0, strategic_target_kwh - soc_at_window_start)

        # Cascading with realistic capacity
        for i in range(len(windows)-2, -1, -1):
            next_i = i + 1
            next_resp = self.window_responsibilities[next_i]['total_responsibility_kwh']
            next_window = windows[next_i]
            next_df = df.loc[next_window['start']:next_window['end']]
            avg_water = next_df['water_heating_kw'].mean()
            avg_load_kw = next_df['adjusted_load_kwh'].mean() / 0.25
            realistic_charge_kw = max(0, max_charge_power_kw - avg_water - avg_load_kw)
            num_slots = len(next_df)
            max_energy = realistic_charge_kw * num_slots * 0.25 * efficiency
            if next_resp > max_energy:
                self.window_responsibilities[i]['total_responsibility_kwh'] += next_resp

        # Strategic carry-forward
        for i in strategic_windows:
            window = windows[i]
            start_idx = window['start']
            soc_at_window_start = df.loc[start_idx, 'simulated_soc_kwh']
            resp = self.window_responsibilities[i]['total_responsibility_kwh']
            soc_after = soc_at_window_start + resp * efficiency
            if soc_after < strategic_target_kwh:
                remaining_energy = strategic_target_kwh - soc_after
                if i + 1 < len(windows):
                    self.window_responsibilities[i + 1]['total_responsibility_kwh'] += remaining_energy / efficiency

        return df
        
    def _pass_5_distribute_charging_in_windows(self, df):
        """
        For each window, sort the slots by price.
        Iteratively assign 'Charge' action to the cheapest slots until the window's
        total charging responsibility (in kWh) is met.

        Args:
            df (pd.DataFrame): DataFrame with allocated responsibilities

        Returns:
            pd.DataFrame: DataFrame with detailed charging assignments
        """
        df['charge_kw'] = 0.0
        max_charge_power_kw = self.battery_config['max_charge_power_kw']

        for resp in self.window_responsibilities:
            window = resp['window']
            total_responsibility_kwh = resp['total_responsibility_kwh']
            window_df = df.loc[window['start']:window['end']].sort_values('import_price_sek_kwh')

            for idx, row in window_df.iterrows():
                if total_responsibility_kwh > 0:
                    charge_kwh_for_slot = max_charge_power_kw * 0.25
                    df.loc[idx, 'charge_kw'] = max_charge_power_kw
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

        for idx, row in df.iterrows():
            pv_kwh = row['adjusted_pv_kwh']
            load_kwh = row['adjusted_load_kwh']
            water_kwh = row['water_heating_kw'] * 0.25
            charge_kw = row['charge_kw']
            import_price = row['import_price_sek_kwh']
            is_cheap = row['is_cheap']

            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
            cycle_adjusted_cost = avg_cost + self.cycle_cost

            action = 'Hold'

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
                net_kwh = pv_kwh - load_kwh - water_kwh

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

            current_kwh = max(min_soc_kwh, min(max_soc_kwh, current_kwh))
            if current_kwh <= 0:
                current_kwh = 0.0
                total_cost = 0.0

            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0

            actions.append(action)
            projected_soc_kwh.append(current_kwh)
            projected_soc_percent.append((current_kwh / capacity_kwh) * 100.0 if capacity_kwh else 0.0)
            projected_battery_cost.append(avg_cost)

        df['action'] = actions
        df['projected_soc_kwh'] = projected_soc_kwh
        df['projected_soc_percent'] = projected_soc_percent
        df['projected_battery_cost'] = projected_battery_cost

        return df

    def _save_schedule_to_json(self, schedule_df):
        """
        Save the final schedule to schedule.json in the required format.

        Args:
            schedule_df (pd.DataFrame): The final schedule DataFrame
        """
        records = dataframe_to_json_response(schedule_df)
        
        with open('schedule.json', 'w') as f:
            json.dump({'schedule': records}, f, indent=2)


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