import json
import math
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import pytz
import requests
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
        self.manual_planning = self.config.get('manual_planning', {}) or {}
        self.learning_config = self.config.get('learning', {})
        self._learning_schema_initialized = False
        self.daily_pv_forecast: dict[str, float] = {}
        self.daily_load_forecast: dict[str, float] = {}
        self._last_temperature_forecast: dict[int, float] = {}
        self.forecast_meta: dict[str, float] = {}

        self._validate_config()

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
        self._max_soc_warning_emitted = False

    def _validate_config(self) -> None:
        """Validate critical configuration values and raise descriptive errors."""
        errors: list[str] = []

        def _ensure_positive(name: str, value: float) -> None:
            if value is None or value <= 0:
                errors.append(f"{name} must be positive (got {value!r})")

        capacity = self.battery_config.get('capacity_kwh')
        _ensure_positive('battery.capacity_kwh', capacity if capacity is not None else 0)

        min_soc = self.battery_config.get('min_soc_percent', 0)
        max_soc = self.battery_config.get('max_soc_percent', 100)
        if not (0 <= min_soc <= max_soc <= 100):
            errors.append(
                f"battery min/max SoC must satisfy 0 ≤ min ≤ max ≤ 100 (got {min_soc}, {max_soc})"
            )

        max_charge_kw = self.battery_config.get('max_charge_power_kw', 0)
        max_discharge_kw = self.battery_config.get('max_discharge_power_kw', 0)
        _ensure_positive('battery.max_charge_power_kw', max_charge_kw)
        _ensure_positive('battery.max_discharge_power_kw', max_discharge_kw)

        inverter_kw = self.config.get('system', {}).get('inverter', {}).get('max_power_kw', 0)
        grid_kw = self.config.get('system', {}).get('grid', {}).get('max_power_kw', 0)
        if inverter_kw:
            _ensure_positive('system.inverter.max_power_kw', inverter_kw)
        if grid_kw:
            _ensure_positive('system.grid.max_power_kw', grid_kw)

        price_smoothing = self.charging_strategy.get('price_smoothing_sek_kwh', 0.0)
        if price_smoothing < 0:
            errors.append("charging_strategy.price_smoothing_sek_kwh must be ≥ 0")

        smoothing_cfg = self.config.get('smoothing', {})
        for key in (
            'min_on_slots_charge',
            'min_off_slots_charge',
            'min_on_slots_discharge',
            'min_off_slots_discharge',
            'min_on_slots_export',
        ):
            value = smoothing_cfg.get(key, 0)
            if value < 0:
                errors.append(f"smoothing.{key} must be ≥ 0")

        manual_cfg = self.config.get('manual_planning', {}) or {}
        for key in ('charge_target_percent', 'export_target_percent'):
            value = manual_cfg.get(key)
            if value is not None:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    errors.append(f"manual_planning.{key} must be a number (got {value!r})")
                    continue
                if not (0.0 <= value <= 100.0):
                    errors.append(f"manual_planning.{key} must be between 0 and 100 (got {value})")


        if errors:
            raise ValueError("Invalid planner configuration:\n - " + "\n - ".join(errors))

    def _learning_enabled(self) -> bool:
        """Return True when learning/sqlite features should be used."""
        learning_cfg = getattr(self, 'learning_config', {})
        return bool(learning_cfg.get('enable', False) and learning_cfg.get('sqlite_path'))

    def _learning_db_path(self) -> str:
        """Return the sqlite path, ensuring directory creation."""
        learning_cfg = getattr(self, 'learning_config', {})
        path = learning_cfg.get('sqlite_path', 'data/planner_learning.db')
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        return path

    def _ensure_learning_schema(self) -> None:
        """Create sqlite tables when learning is enabled."""
        if not self._learning_enabled():
            return
        if getattr(self, '_learning_schema_initialized', False):
            return

        path = self._learning_db_path()
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_planned (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    planned_kwh REAL NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_schedule_planned_date ON schedule_planned(date)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS realized_energy (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_start TEXT NOT NULL,
                    slot_end TEXT NOT NULL,
                    action TEXT,
                    energy_kwh REAL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_water (
                    date TEXT PRIMARY KEY,
                    used_kwh REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS planner_debug (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.commit()

        self._learning_schema_initialized = True

    def _get_daily_water_usage_kwh(self, target_date) -> float:
        """Retrieve recorded water usage for the specified date."""
        if not self._learning_enabled():
            return 0.0

        self._ensure_learning_schema()
        if hasattr(target_date, 'to_pydatetime'):
            target_date = target_date.to_pydatetime().date()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()
        date_key = target_date.isoformat()
        path = self._learning_db_path()
        with sqlite3.connect(path) as conn:
            cur = conn.execute("SELECT used_kwh FROM daily_water WHERE date = ?", (date_key,))
            row = cur.fetchone()
            if row is not None and row[0] is not None:
                return float(row[0])

            conn.execute(
                """
                INSERT OR IGNORE INTO daily_water (date, used_kwh, updated_at)
                VALUES (?, 0, ?)
                """,
                (date_key, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

        return 0.0

    def _record_planned_water_energy(self, target_date, planned_kwh: float) -> None:
        """Persist planned water heating energy for later reconciliation."""
        if not self._learning_enabled() or planned_kwh <= 0:
            return

        self._ensure_learning_schema()
        if hasattr(target_date, 'to_pydatetime'):
            target_date = target_date.to_pydatetime().date()
        elif isinstance(target_date, datetime):
            target_date = target_date.date()
        date_key = target_date.isoformat()
        timestamp = datetime.now(timezone.utc).isoformat()
        path = self._learning_db_path()
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                INSERT INTO schedule_planned (date, planned_kwh, created_at)
                VALUES (?, ?, ?)
                """,
                (date_key, planned_kwh, timestamp),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_water (date, used_kwh, updated_at)
                VALUES (?, 0, ?)
                """,
                (date_key, timestamp),
            )
            conn.execute(
                "UPDATE daily_water SET updated_at = ? WHERE date = ?",
                (timestamp, date_key),
            )
            conn.commit()

    def _fetch_temperature_forecast(self, days_ahead: list[int], tz) -> dict[int, float]:
        """Fetch mean daily temperatures for the requested day offsets."""
        if not days_ahead:
            return {}

        location = self.config.get('system', {}).get('location', {})
        latitude = location.get('latitude')
        longitude = location.get('longitude')
        if latitude is None or longitude is None:
            return {}

        try:
            today = datetime.now(tz).date()
        except Exception:
            today = datetime.now(timezone.utc).date()

        max_offset = max(days_ahead)
        params = {
            'latitude': latitude,
            'longitude': longitude,
            'daily': 'temperature_2m_mean',
            'timezone': self.timezone,
            'forecast_days': max(1, max_offset + 1),
        }

        try:
            response = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            print(f"Warning: Failed to fetch temperature forecast: {exc}")
            return {}

        daily = payload.get('daily', {})
        dates = daily.get('time', [])
        temps = daily.get('temperature_2m_mean', [])

        result: dict[int, float] = {}
        for date_str, temp in zip(dates, temps):
            try:
                date_obj = datetime.fromisoformat(date_str).date()
            except ValueError:
                continue
            offset = (date_obj - today).days
            if offset in days_ahead:
                try:
                    result[offset] = float(temp)
                except (TypeError, ValueError):
                    continue

        return result

    def _calculate_dynamic_s_index(
        self,
        df: pd.DataFrame,
        s_index_cfg: dict,
        max_factor: float,
    ) -> tuple[Optional[float], dict]:
        """Compute dynamic S-index factor based on PV/load deficit and temperature."""
        base_factor = float(s_index_cfg.get('base_factor', s_index_cfg.get('static_factor', 1.05)))
        pv_weight = float(s_index_cfg.get('pv_deficit_weight', 0.0))
        temp_weight = float(s_index_cfg.get('temp_weight', 0.0))
        temp_baseline = float(s_index_cfg.get('temp_baseline_c', 20.0))
        temp_cold = float(s_index_cfg.get('temp_cold_c', -15.0))

        day_offsets = s_index_cfg.get('days_ahead_for_sindex', [2, 3, 4])
        if not isinstance(day_offsets, (list, tuple)):
            day_offsets = [2, 3, 4]

        normalized_days: list[int] = []
        for offset in day_offsets:
            try:
                offset_int = int(offset)
            except (TypeError, ValueError):
                continue
            if offset_int > 0:
                normalized_days.append(offset_int)

        normalized_days = sorted(set(normalized_days))
        if not normalized_days:
            return None, {
                'base_factor': base_factor,
                'reason': 'no_valid_days',
            }

        tz = pytz.timezone(self.timezone)
        try:
            local_index = df.index.tz_convert(tz)
        except TypeError:
            local_index = df.index.tz_localize(tz)
        local_dates = pd.Series(local_index.date, index=df.index)
        today = datetime.now(tz).date()

        daily_pv_map = getattr(self, 'daily_pv_forecast', {}) or {}
        daily_load_map = getattr(self, 'daily_load_forecast', {}) or {}

        deficits: list[float] = []
        considered_days: list[int] = []
        for offset in normalized_days:
            target_date = today + timedelta(days=offset)
            mask = local_dates == target_date
            if mask.any():
                considered_days.append(offset)
                load_sum = float(df.loc[mask, 'adjusted_load_kwh'].sum())
                pv_sum = float(df.loc[mask, 'adjusted_pv_kwh'].sum())
            else:
                key = target_date.isoformat()
                load_sum = float(daily_load_map.get(key, 0.0))
                pv_sum = float(daily_pv_map.get(key, 0.0))
                if load_sum <= 0 and pv_sum <= 0:
                    continue
                considered_days.append(offset)

            if load_sum <= 0:
                deficits.append(0.0)
            else:
                ratio = max(0.0, (load_sum - pv_sum) / max(load_sum, 1e-6))
                deficits.append(ratio)

        if not considered_days:
            return None, {
                'base_factor': base_factor,
                'reason': 'insufficient_forecast_data',
                'requested_days': normalized_days,
            }

        avg_deficit = sum(deficits) / len(deficits) if deficits else 0.0

        temps_map: dict[int, float] = {}
        mean_temp = None
        temp_adjustment = 0.0
        if temp_weight > 0:
            temps_map = self._fetch_temperature_forecast(considered_days, tz)
            temperature_values = [temps_map.get(offset) for offset in considered_days if temps_map.get(offset) is not None]
            if temperature_values:
                mean_temp = sum(temperature_values) / len(temperature_values)
                span = temp_baseline - temp_cold
                if span <= 0:
                    span = 1.0
                temp_adjustment = max(0.0, min(1.0, (temp_baseline - mean_temp) / span))

        self._last_temperature_forecast = temps_map or {}

        raw_factor = base_factor + (pv_weight * avg_deficit) + (temp_weight * temp_adjustment)
        factor = min(max_factor, max(0.0, raw_factor))

        debug_data = {
            'mode': 'dynamic',
            'base_factor': round(base_factor, 4),
            'avg_deficit': round(avg_deficit, 4),
            'pv_deficit_weight': round(pv_weight, 4),
            'temp_weight': round(temp_weight, 4),
            'temp_adjustment': round(temp_adjustment, 4),
            'mean_temperature_c': round(mean_temp, 2) if mean_temp is not None else None,
            'considered_days': considered_days,
            'requested_days': normalized_days,
            'temperatures': {str(k): v for k, v in temps_map.items()} if temps_map else None,
            'factor_unclamped': round(raw_factor, 4),
        }

        return factor, debug_data

    def _record_debug_payload(self, payload: dict) -> None:
        """Persist planner debug payloads for observability."""
        if not self._learning_enabled():
            return

        self._ensure_learning_schema()
        timestamp = datetime.now(timezone.utc).isoformat()
        path = self._learning_db_path()
        with sqlite3.connect(path) as conn:
            conn.execute(
                """
                INSERT INTO planner_debug (created_at, payload)
                VALUES (?, ?)
                """,
                (timestamp, json.dumps(payload)),
            )
            conn.commit()

    def _remaining_responsibility_after(self, idx) -> float:
        """Return remaining responsibility energy (kWh) for windows at or after idx."""
        total = 0.0
        for entry in getattr(self, 'window_responsibilities', []):
            start = entry.get('window', {}).get('start')
            if start is not None and start >= idx:
                total += float(entry.get('total_responsibility_kwh', 0.0))
        return total

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
        max_soc_percent = self.battery_config.get('max_soc_percent')
        current_soc = self.state.get('battery_soc_percent')
        try:
            if (
                current_soc is not None
                and max_soc_percent is not None
                and float(current_soc) > float(max_soc_percent) + 0.1
                and not self._max_soc_warning_emitted
            ):
                print(
                    f"Warning: current battery SoC ({float(current_soc):.2f}%) exceeds configured "
                    f"max_soc_percent ({float(max_soc_percent):.2f}%). "
                    "Planner will respect the live SoC and prevent further charging above the configured limit."
                )
                self._max_soc_warning_emitted = True
        except (TypeError, ValueError):
            pass
        self.daily_pv_forecast = input_data.get('daily_pv_forecast', {})
        self.daily_load_forecast = input_data.get('daily_load_forecast', {})
        # Compute 'now' rounded up to next 15-minute slot in configured timezone
        try:
            now_slot = pd.Timestamp.now(tz=self.timezone).ceil('15min')
        except Exception:
            now_slot = pd.Timestamp.now(tz='Europe/Stockholm').ceil('15min')
        self.now_slot = now_slot
        df = self._pass_0_apply_safety_margins(df)
        df = self._pass_1_identify_windows(df)
        df = self._pass_2_schedule_water_heating(df)
        df = self._pass_3_simulate_baseline_depletion(df)
        df = self._pass_4_allocate_cascading_responsibilities(df)
        df = self._pass_5_distribute_charging_in_windows(df)
        df = self._pass_6_finalize_schedule(df)
        df = self._pass_7_enforce_hysteresis(df)
        df = self._apply_soc_target_percent(df)
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
        price_smoothing_sek_kwh = self.charging_strategy.get('price_smoothing_sek_kwh', 0.05)

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
        Schedule water heating in contiguous blocks per day (today + limited days ahead).

        Args:
            df (pd.DataFrame): DataFrame with prepared data

        Returns:
            pd.DataFrame: Updated DataFrame with water heating schedule
        """
        df = df.copy()

        timezone_name = getattr(self, 'timezone', 'Europe/Stockholm')
        tz = pytz.timezone(timezone_name)

        power_kw = self.water_heating_config.get('power_kw', 3.0)
        min_hours_per_day = self.water_heating_config.get('min_hours_per_day', 2.0)
        min_kwh_per_day = self.water_heating_config.get('min_kwh_per_day', power_kw * min_hours_per_day)
        max_blocks_per_day = self.water_heating_config.get('max_blocks_per_day', 2)
        schedule_future_only = self.water_heating_config.get('schedule_future_only', True)
        defer_up_to_hours = float(self.water_heating_config.get('defer_up_to_hours', 0))
        plan_days_ahead = int(self.water_heating_config.get('plan_days_ahead', 1))
        plan_days_ahead = max(0, min(plan_days_ahead, 1))  # Horizon limited to tomorrow

        slot_minutes = self.config.get('nordpool', {}).get('resolution_minutes', 15) or 15
        slot_duration = pd.Timedelta(minutes=slot_minutes)
        slot_energy_kwh = power_kw * (slot_duration.total_seconds() / 3600.0)
        slots_per_block = max(1, math.ceil(min_kwh_per_day / slot_energy_kwh))

        # Build local datetime mapping for scheduling decisions
        try:
            local_datetimes = df.index.tz_convert(tz)
        except TypeError:
            local_datetimes = df.index.tz_localize(tz)
        local_dates = pd.Series(local_datetimes.date, index=df.index)

        now_slot = getattr(self, 'now_slot', df.index[0])
        df['water_heating_kw'] = 0.0
        planned_energy_by_date: dict[datetime.date, float] = {}

        try:
            now_local = now_slot.tz_convert(tz)
        except TypeError:
            now_local = now_slot.tz_localize(tz)
        today_local = now_local.normalize()
        global_limit_local = today_local + pd.Timedelta(hours=48)

        daily_water_kwh_today = self._get_daily_water_usage_kwh(today_local.date())

        def _has_full_price_day(start_local: pd.Timestamp) -> bool:
            base_end = start_local + pd.Timedelta(days=1)
            base_mask = (local_datetimes >= start_local) & (local_datetimes < base_end)
            expected_slots = int(round((base_end - start_local) / slot_duration))
            return base_mask.sum() >= expected_slots

        for day_offset in range(0, plan_days_ahead + 1):
            day_start_local = today_local + pd.Timedelta(days=day_offset)
            if day_start_local >= global_limit_local:
                break

            base_end_local = day_start_local + pd.Timedelta(days=1)
            day_horizon_local = min(base_end_local + pd.Timedelta(hours=max(0.0, defer_up_to_hours)), global_limit_local)

            day_mask = (local_datetimes >= day_start_local) & (local_datetimes < day_horizon_local)
            day_slots = df.loc[day_mask]
            if day_slots.empty:
                continue

            if day_offset > 0 and not _has_full_price_day(day_start_local):
                continue  # skip if tomorrow's prices are not yet known

            if schedule_future_only:
                day_slots = day_slots[day_slots.index > now_slot]
                if day_slots.empty:
                    continue

            if day_offset == 0:
                remaining_energy = max(0.0, min_kwh_per_day - daily_water_kwh_today)
            else:
                remaining_energy = min_kwh_per_day

            if remaining_energy <= 0:
                continue

            required_slots = max(1, math.ceil(remaining_energy / slot_energy_kwh))

            cheap_slots = day_slots[day_slots['is_cheap']].copy()
            if cheap_slots.empty:
                continue

            # Step 1: Sort cheap slots by price (cheapest first) - NOT by time!
            cheap_slots_sorted = cheap_slots.sort_values('import_price_sek_kwh')
            
            # Step 2: Select optimal slots with contiguity preference
            selected_slots = self._select_optimal_water_slots(
                cheap_slots_sorted, required_slots, max_blocks_per_day, slot_duration
            )
            
            if len(selected_slots) == 0:
                # Not enough capacity to satisfy the requirement for this day; skip scheduling.
                continue

            # Step 3: Apply selected slots to DataFrame
            for slot_time in selected_slots:
                if slot_time not in df.index:
                    continue
                df.loc[slot_time, 'water_heating_kw'] = power_kw
                local_date = local_dates.loc[slot_time]
                planned_energy_by_date[local_date] = planned_energy_by_date.get(local_date, 0.0) + slot_energy_kwh

        for target_date, planned_kwh in planned_energy_by_date.items():
            self._record_planned_water_energy(target_date, planned_kwh)

        return df
    
    def _select_optimal_water_slots(self, cheap_slots_sorted, slots_needed, max_blocks_per_day, slot_duration):
        """
        Select optimal water heating slots prioritizing cheapest prices while 
        preferring contiguity where it doesn't significantly increase cost.
        
        Args:
            cheap_slots_sorted (pd.DataFrame): Cheap slots sorted by price (cheapest first)
            slots_needed (int): Number of slots required
            max_blocks_per_day (int): Maximum number of blocks allowed
            slot_duration (pd.Timedelta): Duration of each slot
            
        Returns:
            list[pd.Timestamp]: Selected slot times
        """
        selected_slots = []
        remaining_slots = slots_needed
        
        # Greedy selection with contiguity preference
        for _, slot in cheap_slots_sorted.iterrows():
            if remaining_slots <= 0:
                break
                
            slot_time = slot.name
            
            # Check if this slot extends an existing block
            extends_existing = any(
                abs((slot_time - existing_time) == slot_duration)
                for existing_time in selected_slots
            )
            
            # Always select cheapest slots, but prefer contiguity when possible
            # The contiguity preference is handled in the consolidation phase
            selected_slots.append(slot_time)
            remaining_slots -= 1
        
        # If we have more than max_blocks, consolidate to cheapest blocks
        if len(selected_slots) > 0:
            selected_slots = self._consolidate_to_blocks(
                selected_slots, max_blocks_per_day, slot_duration, cheap_slots_sorted
            )
        
        return selected_slots
    
    def _consolidate_to_blocks(self, selected_slots, max_blocks, slot_duration, cheap_slots_sorted):
        """
        Group selected slots into up to max_blocks contiguous groups.
        If too many blocks, merge the ones with minimal cost penalty.
        
        Args:
            selected_slots (list): List of selected slot times
            max_blocks (int): Maximum number of blocks allowed
            slot_duration (pd.Timedelta): Duration of each slot
            cheap_slots_sorted (pd.DataFrame): Cheap slots with price data
            
        Returns:
            list[pd.Timestamp]: Consolidated slot times
        """
        if len(selected_slots) <= 1:
            return selected_slots
        
        # Sort by time for block creation
        selected_slots_sorted = sorted(selected_slots)
        
        # Create initial blocks
        blocks = []
        current_block = [selected_slots_sorted[0]]
        
        for slot_time in selected_slots_sorted[1:]:
            if len(current_block) > 0 and (slot_time - current_block[-1]) == slot_duration:
                current_block.append(slot_time)
            else:
                blocks.append(current_block)
                current_block = [slot_time]
        
        blocks.append(current_block)
        
        # If we have too many blocks, merge the ones with minimal cost penalty
        while len(blocks) > max_blocks:
            merge_idx = self._find_best_merge(blocks, cheap_slots_sorted, slot_duration)
            if merge_idx is not None:
                blocks = self._merge_blocks(blocks, merge_idx)
            else:
                break
        
        # Flatten blocks back to slot list
        consolidated_slots = []
        for block in blocks:
            consolidated_slots.extend(block)
        
        return consolidated_slots
    
    def _find_best_merge(self, blocks, cheap_slots_sorted, slot_duration):
        """
        Find the best pair of blocks to merge with minimal cost penalty.
        
        Args:
            blocks (list): List of blocks (each block is list of slot times)
            cheap_slots_sorted (pd.DataFrame): Cheap slots with price data
            slot_duration (pd.Timedelta): Duration of each slot
            
        Returns:
            int: Index of first block to merge (None if no good merge found)
        """
        if len(blocks) < 2:
            return None
        
        best_merge_idx = None
        best_merge_cost = float('inf')
        
        for i in range(len(blocks) - 1):
            block1 = blocks[i]
            block2 = blocks[i + 1]
            
            # Calculate cost of current arrangement
            current_cost = self._calculate_block_cost(block1, cheap_slots_sorted) + \
                        self._calculate_block_cost(block2, cheap_slots_sorted)
            
            # Calculate cost if merged (would need to fill gap)
            gap_start = block1[-1] + slot_duration
            gap_end = block2[0]
            gap_slots_needed = int((gap_end - gap_start) / slot_duration)
            
            # Find cheapest slots to fill the gap
            gap_cost = 0
            if gap_slots_needed > 0:
                gap_slots = cheap_slots_sorted[
                    (cheap_slots_sorted.index >= gap_start) & 
                    (cheap_slots_sorted.index < gap_end)
                ].head(gap_slots_needed)
                gap_cost = gap_slots['import_price_sek_kwh'].sum()
            
            merged_cost = current_cost + gap_cost
            
            if merged_cost < best_merge_cost:
                best_merge_cost = merged_cost
                best_merge_idx = i
        
        return best_merge_idx
    
    def _merge_blocks(self, blocks, merge_idx):
        """
        Merge two adjacent blocks at the specified index.
        
        Args:
            blocks (list): List of blocks
            merge_idx (int): Index of first block to merge
            
        Returns:
            list: Updated blocks list
        """
        if merge_idx >= len(blocks) - 1:
            return blocks
        
        # Merge block at merge_idx with merge_idx + 1
        merged_block = blocks[merge_idx] + blocks[merge_idx + 1]
        
        # Create new blocks list
        new_blocks = blocks[:merge_idx] + [merged_block] + blocks[merge_idx + 2:]
        
        return new_blocks
    
    def _calculate_block_cost(self, block, cheap_slots_sorted):
        """
        Calculate total cost of a block using price data.
        
        Args:
            block (list): List of slot times in block
            cheap_slots_sorted (pd.DataFrame): Cheap slots with price data
            
        Returns:
            float: Total cost of the block
        """
        if not block:
            return 0.0
        
        block_prices = cheap_slots_sorted.loc[block]['import_price_sek_kwh']
        return block_prices.sum()
        
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
        strategic_target_soc_percent = self.strategic_charging.get('target_soc_percent', max_soc_percent)
        strategic_target_kwh = strategic_target_soc_percent / 100.0 * capacity_kwh

        min_soc_kwh = min_soc_percent / 100.0 * capacity_kwh
        max_soc_kwh = max_soc_percent / 100.0 * capacity_kwh
        battery_use_margin_sek = self.thresholds.get('battery_use_margin_sek', 0.10)
        max_discharge_power_kw = self.battery_config.get('max_discharge_power_kw', 5.0)
        battery_cost = self.state['battery_cost_sek_per_kwh']
        economic_threshold = battery_cost + self.cycle_cost + battery_use_margin_sek
        max_discharge_power_kw = self.battery_config.get('max_discharge_power_kw', 5.0)

        current_kwh = self.state['battery_kwh']
        soc_list = []
        window_start_states = []

        now_slot = getattr(self, 'now_slot', df.index[0])
        for idx, row in df.iterrows():
            if idx < now_slot:
                # Keep SoC unchanged before 'now' as initial_state already reflects history
                soc_list.append(current_kwh)
                continue
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
                rate_limited_output = max_discharge_power_kw * 0.25
                available_output = self._battery_output_from_energy(max(0.0, current_kwh - min_soc_kwh))
                deliverable_kwh = min(deficit_kwh, rate_limited_output, available_output)
                if deliverable_kwh > 0:
                    discharge_from_battery = self._battery_energy_for_output(deliverable_kwh)
                    current_kwh -= discharge_from_battery

            # Case 2: Surplus
            surplus_kwh = adjusted_pv - adjusted_load - water_kwh
            if surplus_kwh > 0 and self.charge_efficiency > 0:
                charge_to_battery = self._energy_into_battery(surplus_kwh)
                available_capacity = max(0.0, max_soc_kwh - current_kwh)
                charge_to_battery = min(charge_to_battery, available_capacity)
                if charge_to_battery > 0:
                    current_kwh += charge_to_battery

            # Lower bound only; allow SoC to remain above configured max if current state is already there.
            if current_kwh < min_soc_kwh:
                current_kwh = min_soc_kwh
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
        # Group future slots into windows only (skip past)
        windows = []
        current_window = None
        now_slot = getattr(self, 'now_slot', df.index[0])
        for idx, row in df.iterrows():
            if idx < now_slot:
                continue
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

        # S-index factor (static or dynamic)
        s_index_cfg = self.config.get('s_index', {})
        s_index_mode = (s_index_cfg.get('mode') or 'static').lower()
        s_index_max = float(s_index_cfg.get('max_factor', 1.50))
        static_factor = float(s_index_cfg.get('static_factor', 1.05))
        base_factor = float(s_index_cfg.get('base_factor', static_factor))

        s_index_factor = min(static_factor, s_index_max)
        s_index_debug = {
            'mode': s_index_mode,
            'static_factor': round(static_factor, 4),
            'base_factor': round(base_factor, 4),
            'max_factor': round(s_index_max, 4),
        }

        if s_index_mode == 'dynamic':
            dynamic_factor, dynamic_debug = self._calculate_dynamic_s_index(df, s_index_cfg, s_index_max)
            if dynamic_factor is not None:
                s_index_factor = dynamic_factor
                s_index_debug.update(dynamic_debug)
            else:
                s_index_factor = min(static_factor, s_index_max)
                s_index_debug['fallback'] = 'static'

        s_index_debug['factor'] = round(s_index_factor, 4)
        self.s_index_debug = s_index_debug

        # Calculate price-aware gap responsibilities
        self.window_responsibilities = []
        capacity_kwh = self.battery_config.get('capacity_kwh', 10.0)
        min_soc_percent = self.battery_config.get('min_soc_percent', 15)
        max_soc_percent = self.battery_config.get('max_soc_percent', 95)
        strategic_target_soc_percent = self.strategic_charging.get(
            'target_soc_percent', max_soc_percent
        )
        strategic_target_kwh = strategic_target_soc_percent / 100.0 * capacity_kwh

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
        tolerance = self.charging_strategy.get('block_consolidation_tolerance_sek')
        if tolerance is None:
            tolerance = self.charging_strategy.get('price_smoothing_sek_kwh', 0.05)
        max_gap_slots = int(self.charging_strategy.get('consolidation_max_gap_slots', 0) or 0)
        now_slot = getattr(self, 'now_slot', df.index[0])

        for resp in self.window_responsibilities:
            window = resp['window']
            total_responsibility_kwh = float(resp['total_responsibility_kwh'])
            if total_responsibility_kwh <= 0:
                continue

            window_df = df.loc[window['start']:window['end']]
            window_df = window_df[window_df.index >= now_slot]
            if window_df.empty:
                continue

            indices = list(window_df.index)
            slot_capacities = []
            slot_prices = []
            for idx, row in window_df.iterrows():
                available_kw = min(self._available_charge_power_kw(row), max_charge_power_kw)
                slot_capacities.append(max(0.0, available_kw * 0.25))
                slot_prices.append(row['import_price_sek_kwh'])

            best_segment = None
            fallback_segment = None
            n = len(indices)
            for left in range(n):
                if slot_capacities[left] <= 0:
                    continue
                total_cap = 0.0
                weighted_price = 0.0
                min_price = slot_prices[left]
                max_price = slot_prices[left]
                gap_streak = 0
                for right in range(left, n):
                    capacity = slot_capacities[right]
                    if capacity <= 0:
                        gap_streak += 1
                        if gap_streak > max_gap_slots:
                            break
                        continue

                    gap_streak = 0
                    total_cap += capacity
                    weighted_price += capacity * slot_prices[right]
                    min_price = min(min_price, slot_prices[right])
                    max_price = max(max_price, slot_prices[right])

                    if total_cap + 1e-9 >= total_responsibility_kwh:
                        avg_price = weighted_price / total_cap if total_cap > 0 else float('inf')
                        price_span = max_price - min_price
                        candidate = {
                            'left': left,
                            'right': right,
                            'avg_price': avg_price,
                            'total_capacity': total_cap,
                            'price_span': price_span,
                        }
                        if price_span <= tolerance:
                            if (
                                best_segment is None
                                or avg_price < best_segment['avg_price'] - 1e-9
                                or (
                                    abs(avg_price - best_segment['avg_price']) < 1e-9
                                    and (right - left) < (best_segment['right'] - best_segment['left'])
                                )
                            ):
                                best_segment = candidate
                        if (
                            fallback_segment is None
                            or avg_price < fallback_segment['avg_price'] - 1e-9
                        ):
                            fallback_segment = candidate
                        break

            chosen_segment = best_segment or fallback_segment
            if chosen_segment is None:
                # Fallback to original price-sorted allocation if no segment could be found
                window_sorted = window_df.sort_values('import_price_sek_kwh')
                remaining = total_responsibility_kwh
                for idx, row in window_sorted.iterrows():
                    if idx < now_slot:
                        continue
                    available_kw = min(self._available_charge_power_kw(row), max_charge_power_kw)
                    charge_kwh_for_slot = min(available_kw * 0.25, remaining)
                    if charge_kwh_for_slot <= 0:
                        continue
                    df.loc[idx, 'charge_kw'] = charge_kwh_for_slot / 0.25
                    remaining -= charge_kwh_for_slot
                    if remaining <= 1e-6:
                        break
                continue

            remaining = total_responsibility_kwh
            for pos in range(chosen_segment['left'], chosen_segment['right'] + 1):
                idx = indices[pos]
                capacity_kwh = slot_capacities[pos]
                if capacity_kwh <= 0:
                    continue
                charge_kwh_for_slot = min(capacity_kwh, remaining)
                if charge_kwh_for_slot <= 0:
                    continue
                df.loc[idx, 'charge_kw'] = charge_kwh_for_slot / 0.25
                remaining -= charge_kwh_for_slot
                if remaining <= 1e-6:
                    break

            if remaining > 1e-6:
                # Fill any residual energy using price order without disturbing existing assignments
                window_sorted = window_df.sort_values('import_price_sek_kwh')
                for idx, row in window_sorted.iterrows():
                    if idx < now_slot:
                        continue
                    available_kw = min(self._available_charge_power_kw(row), max_charge_power_kw)
                    max_kwh = available_kw * 0.25
                    already_assigned_kwh = df.loc[idx, 'charge_kw'] * 0.25
                    remaining_capacity = max(0.0, max_kwh - already_assigned_kwh)
                    if remaining_capacity <= 0:
                        continue
                    charge_kwh_for_slot = min(remaining_capacity, remaining)
                    if charge_kwh_for_slot <= 0:
                        continue
                    df.loc[idx, 'charge_kw'] = (already_assigned_kwh + charge_kwh_for_slot) / 0.25
                    remaining -= charge_kwh_for_slot
                    if remaining <= 1e-6:
                        break

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

        strategic_target_soc_percent = self.strategic_charging.get('target_soc_percent', max_soc_percent)
        strategic_target_kwh = strategic_target_soc_percent / 100.0 * capacity_kwh

        min_soc_kwh = min_soc_percent / 100.0 * capacity_kwh
        max_soc_kwh = max_soc_percent / 100.0 * capacity_kwh
        battery_use_margin_sek = self.thresholds.get('battery_use_margin_sek', 0.10)
        max_discharge_power_kw = self.battery_config.get('max_discharge_power_kw', 5.0)

        actions = []
        projected_soc_kwh = []
        projected_soc_percent = []
        projected_battery_cost = []
        water_from_pv = []
        water_from_battery = []
        water_from_grid = []
        export_kwh = []
        export_revenue = []
        # Battery power telemetry (kW)
        battery_charge_kw_series = []
        battery_discharge_kw_series = []

        # Calculate protective SoC for export
        arbitrage_config = self.config.get('arbitrage', {})
        enable_export = arbitrage_config.get('enable_export', True)
        protective_soc_strategy = arbitrage_config.get('protective_soc_strategy', 'gap_based')
        fixed_protective_soc_percent = arbitrage_config.get('fixed_protective_soc_percent', 15.0)
        export_percentile_threshold = float(arbitrage_config.get('export_percentile_threshold', 15.0))
        export_peak_only = arbitrage_config.get('enable_peak_only_export', True)
        export_future_price_guard = arbitrage_config.get('export_future_price_guard', False)
        future_price_guard_buffer = float(arbitrage_config.get('future_price_guard_buffer_sek', 0.0))

        manual_cfg = getattr(self, 'manual_planning', None)
        if not manual_cfg:
            manual_cfg = self.config.get('manual_planning', {}) or {}
            self.manual_planning = manual_cfg
        def _clamp_manual(value: Optional[float], fallback: float) -> float:
            if value is None:
                return fallback
            try:
                val = float(value)
            except (TypeError, ValueError):
                return fallback
            return max(min_soc_percent, min(max_soc_percent, val))

        manual_charge_target_percent = _clamp_manual(
            manual_cfg.get('charge_target_percent'),
            max_soc_percent,
        )
        manual_export_target_percent = _clamp_manual(
            manual_cfg.get('export_target_percent'),
            min_soc_percent,
        )
        manual_export_target_kwh = manual_export_target_percent / 100.0 * capacity_kwh
        # Manual-mode toggles
        override_hold_in_cheap = bool(manual_cfg.get('override_hold_in_cheap', True))
        force_discharge_on_deficit = bool(manual_cfg.get('force_discharge_on_deficit', True))

        peak_price_threshold = None
        if export_peak_only and 0 < export_percentile_threshold < 100:
            quantile = max(0.0, min(1.0, 1.0 - (export_percentile_threshold / 100.0)))
            peak_price_threshold = df['import_price_sek_kwh'].quantile(quantile)
            if pd.isna(peak_price_threshold):
                peak_price_threshold = None

        if protective_soc_strategy == 'gap_based':
            # Calculate protective SoC based on future responsibilities
            future_responsibilities = sum(resp['total_responsibility_kwh'] for resp in getattr(self, 'window_responsibilities', []))
            protective_soc_kwh = max(min_soc_kwh, future_responsibilities * 1.1)  # 10% buffer
        else:
            protective_soc_kwh = fixed_protective_soc_percent / 100.0 * capacity_kwh

        now_slot = getattr(self, 'now_slot', df.index[0])
        entry_soc_kwh_series: list[float] = []
        entry_soc_percent_series: list[float] = []
        manual_request_series: list[Optional[str]] = []
        for idx, row in df.iterrows():
            # Do not modify or simulate past slots; preserve initial SoC/cost at 'now'
            entry_soc_kwh_series.append(current_kwh)
            entry_soc_percent_series.append((current_kwh / capacity_kwh) * 100.0 if capacity_kwh else 0.0)
            if idx < now_slot:
                actions.append('Hold')
                projected_soc_kwh.append(current_kwh)
                projected_soc_percent.append((current_kwh / capacity_kwh) * 100.0 if capacity_kwh else 0.0)
                projected_battery_cost.append(total_cost / current_kwh if current_kwh > 0 else 0.0)
                water_from_pv.append(0.0)
                water_from_battery.append(0.0)
                water_from_grid.append(0.0)
                export_kwh.append(0.0)
                export_revenue.append(0.0)
                battery_charge_kw_series.append(0.0)
                battery_discharge_kw_series.append(0.0)
                manual_request_series.append(None)
                continue
            pv_kwh = row['adjusted_pv_kwh']
            load_kwh = row['adjusted_load_kwh']
            water_kwh_required = row['water_heating_kw'] * 0.25
            charge_kw = row['charge_kw']
            import_price = row['import_price_sek_kwh']
            export_price = row['export_price_sek_kwh']
            is_cheap = row['is_cheap']
            manual_action_raw = row.get('manual_action')
            manual_action = None
            if isinstance(manual_action_raw, str):
                manual_action = manual_action_raw.strip().lower()
            manual_request_series.append(manual_action)

            discharge_rate_limit_kwh = max_discharge_power_kw * 0.25
            available_battery_energy = max(0.0, current_kwh - min_soc_kwh)
            available_output_kwh = self._battery_output_from_energy(available_battery_energy)
            discharge_budget_kwh = min(discharge_rate_limit_kwh, available_output_kwh)

            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
            cycle_adjusted_cost = avg_cost + self.cycle_cost

            action = 'Hold'
            slot_export_kwh = 0.0
            slot_export_revenue = 0.0

            # Water heating source selection: PV surplus → battery (economical) → grid
            water_from_pv_kwh = 0.0
            water_from_battery_kwh = 0.0
            water_from_grid_kwh = 0.0

            manual_hold = manual_action == 'hold'
            if manual_hold:
                charge_kw = 0.0
            manual_export_requested = manual_action == 'export'
            if manual_export_requested:
                charge_kw = 0.0

            if water_kwh_required > 0:
                # Step 1: Use PV surplus first
                pv_surplus = max(0.0, pv_kwh - load_kwh)
                water_from_pv_kwh = min(water_kwh_required, pv_surplus)
                remaining_water = water_kwh_required - water_from_pv_kwh

                # Step 2: Use battery if economical
                battery_allowed_for_water = not is_cheap and not manual_hold
                if remaining_water > 0 and battery_allowed_for_water and self.discharge_efficiency > 0:
                    battery_water_threshold = avg_cost + self.cycle_cost + self.thresholds.get('battery_water_margin_sek', 0.20)
                    if import_price > battery_water_threshold:
                        battery_available = min(remaining_water, discharge_budget_kwh)
                        if battery_available > 0:
                            water_from_battery_kwh = battery_available
                            battery_energy_used = self._battery_energy_for_output(battery_available)
                            total_cost -= avg_cost * battery_energy_used
                            total_cost = max(0.0, total_cost)
                            current_kwh -= battery_energy_used
                            remaining_water -= battery_available
                            discharge_budget_kwh = max(0.0, discharge_budget_kwh - battery_available)
                            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
                            cycle_adjusted_cost = avg_cost + self.cycle_cost
            else:
                remaining_water = 0.0

            # Step 3: Use grid for remaining
            water_from_grid_kwh = remaining_water

            # Calculate net after water heating sources
            net_kwh = pv_kwh - load_kwh - water_from_pv_kwh - water_from_battery_kwh - water_from_grid_kwh

            # Track per-slot battery in/out
            slot_batt_charge_kwh = 0.0
            slot_batt_discharge_kwh = 0.0
            slot_export_kwh = 0.0
            slot_export_revenue = 0.0

            pv_surplus_remaining = max(0.0, net_kwh)

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
                    avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
                    cycle_adjusted_cost = avg_cost + self.cycle_cost
                    action = 'Charge'
                    slot_batt_charge_kwh += stored_energy
            else:
                if net_kwh < 0 and self.discharge_efficiency > 0 and not manual_hold:
                    # Determine if manual mode is active (any manual_action provided in input df)
                    try:
                        manual_mode_active = df['manual_action'].notna().any()
                    except Exception:
                        manual_mode_active = False

                    if manual_mode_active and force_discharge_on_deficit:
                        # Force discharge up to the slot budget regardless of cheap/price guards
                        deficit_kwh = -net_kwh
                        deliverable_kwh = min(deficit_kwh, discharge_budget_kwh)
                        if deliverable_kwh > 0:
                            battery_energy_used = self._battery_energy_for_output(deliverable_kwh)
                            total_cost -= avg_cost * battery_energy_used
                            total_cost = max(0.0, total_cost)
                            current_kwh -= battery_energy_used
                            discharge_budget_kwh = max(0.0, discharge_budget_kwh - deliverable_kwh)
                            net_kwh += deliverable_kwh
                            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
                            cycle_adjusted_cost = avg_cost + self.cycle_cost
                            action = 'Discharge'
                            slot_batt_discharge_kwh += deliverable_kwh
                    else:
                        cheap_guard_ok = (not is_cheap) or (manual_mode_active and override_hold_in_cheap)
                        if cheap_guard_ok:
                            discharge_price_threshold = cycle_adjusted_cost + battery_use_margin_sek
                            if import_price > discharge_price_threshold:
                                deficit_kwh = -net_kwh
                                deliverable_kwh = min(deficit_kwh, discharge_budget_kwh)
                                if deliverable_kwh > 0:
                                    battery_energy_used = self._battery_energy_for_output(deliverable_kwh)
                                    total_cost -= avg_cost * battery_energy_used
                                    total_cost = max(0.0, total_cost)
                                    current_kwh -= battery_energy_used
                                    discharge_budget_kwh = max(0.0, discharge_budget_kwh - deliverable_kwh)
                                    net_kwh += deliverable_kwh
                                    avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
                                    cycle_adjusted_cost = avg_cost + self.cycle_cost
                                    action = 'Discharge'
                                    slot_batt_discharge_kwh += deliverable_kwh
                elif net_kwh > 0 and self.charge_efficiency > 0:
                    stored_energy = self._energy_into_battery(net_kwh)
                    available_capacity = max(0.0, max_soc_kwh - current_kwh)
                    stored_energy = min(stored_energy, available_capacity)
                    if stored_energy > 0:
                        current_kwh += stored_energy
                        pv_energy_used = stored_energy / self.charge_efficiency if self.charge_efficiency > 0 else 0.0
                        net_kwh = max(0.0, net_kwh - pv_energy_used)
                        action = 'PV Charge'
                        slot_batt_charge_kwh += stored_energy

            # Export logic: Check for profitable export when safe
            manual_export_applied = False
            if manual_export_requested:
                export_fees = arbitrage_config.get('export_fees_sek_per_kwh', 0.0)
                net_export_price = export_price - export_fees
                manual_floor_kwh = max(min_soc_kwh, manual_export_target_kwh)
                available_manual_energy = max(0.0, current_kwh - manual_floor_kwh)
                if available_manual_energy > 0 and discharge_budget_kwh > 0:
                    manual_output_cap = min(
                        discharge_budget_kwh,
                        self._battery_output_from_energy(available_manual_energy),
                    )
                    if manual_output_cap > 0:
                        export_from_battery = manual_output_cap
                        slot_export_kwh = export_from_battery
                        slot_export_revenue = slot_export_kwh * net_export_price
                        battery_energy_used = self._battery_energy_for_output(export_from_battery)
                        battery_energy_used = min(battery_energy_used, available_manual_energy)
                        current_kwh = max(min_soc_kwh, current_kwh - battery_energy_used)
                        total_cost -= avg_cost * battery_energy_used
                        discharge_budget_kwh = max(0.0, discharge_budget_kwh - export_from_battery)
                        avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
                        cycle_adjusted_cost = avg_cost + self.cycle_cost
                        slot_batt_discharge_kwh += export_from_battery
                        total_cost = max(0.0, total_cost)
                        action = 'Export'
                        manual_export_applied = True

            if enable_export and not manual_export_applied:
                export_fees = arbitrage_config.get('export_fees_sek_per_kwh', 0.0)
                export_profit_margin = arbitrage_config.get('export_profit_margin_sek', 0.05)
                net_export_price = export_price - export_fees
                protective_headroom_stored = max(0.0, current_kwh - protective_soc_kwh)
                if charge_kw <= 0:
                    battery_export_capacity = min(
                        discharge_budget_kwh,
                        self._battery_output_from_energy(protective_headroom_stored),
                    )
                else:
                    battery_export_capacity = 0.0

                battery_threshold = cycle_adjusted_cost + export_profit_margin

                can_export_battery = (
                    battery_export_capacity > 0 and
                    net_export_price > battery_threshold
                )

                if can_export_battery and export_peak_only and peak_price_threshold is not None:
                    can_export_battery = import_price >= peak_price_threshold

                if can_export_battery and export_future_price_guard:
                    future_prices = df.loc[idx:, 'import_price_sek_kwh']
                    future_max_price = future_prices.max()
                    if future_max_price is not None:
                        can_export_battery = net_export_price >= (future_max_price - future_price_guard_buffer)

                if can_export_battery:
                    remaining_resp = self._remaining_responsibility_after(idx)
                    responsibilities_met = remaining_resp <= 0.01
                    strategic_ready = current_kwh >= strategic_target_kwh
                    guard_floor = max(protective_soc_kwh, strategic_target_kwh)
                    available_for_export = max(0.0, current_kwh - guard_floor)
                    export_from_battery = min(battery_export_capacity, available_for_export)

                    if export_from_battery > 0 and responsibilities_met and strategic_ready:
                        slot_export_kwh = export_from_battery
                        slot_export_revenue = slot_export_kwh * net_export_price
                        battery_energy_used = self._battery_energy_for_output(export_from_battery)
                        current_kwh -= battery_energy_used
                        total_cost -= avg_cost * battery_energy_used
                        discharge_budget_kwh = max(0.0, discharge_budget_kwh - export_from_battery)
                        avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0
                        cycle_adjusted_cost = avg_cost + self.cycle_cost
                        slot_batt_discharge_kwh += export_from_battery
                        total_cost = max(0.0, total_cost)
                        action = 'Export'
                if manual_export_requested and action != 'Export':
                    action = 'Export'

            # Spill remaining PV surplus without explicit export planning
            if pv_surplus_remaining > 0:
                net_kwh = 0.0

            if current_kwh < min_soc_kwh:
                current_kwh = min_soc_kwh
            if current_kwh <= 0:
                current_kwh = 0.0
                total_cost = 0.0

            avg_cost = total_cost / current_kwh if current_kwh > 0 else 0.0

            # Include battery for water-from-battery
            if water_from_battery_kwh > 0:
                slot_batt_discharge_kwh += water_from_battery_kwh

            actions.append(action)
            projected_soc_kwh.append(current_kwh)
            projected_soc_percent.append((current_kwh / capacity_kwh) * 100.0 if capacity_kwh else 0.0)
            projected_battery_cost.append(avg_cost)
            water_from_pv.append(water_from_pv_kwh)
            water_from_battery.append(water_from_battery_kwh)
            water_from_grid.append(water_from_grid_kwh)
            export_kwh.append(slot_export_kwh)
            export_revenue.append(slot_export_revenue)
            battery_charge_kw_series.append(slot_batt_charge_kwh / 0.25)
            battery_discharge_kw_series.append(slot_batt_discharge_kwh / 0.25)

        df['action'] = actions
        df['projected_soc_kwh'] = projected_soc_kwh
        df['projected_soc_percent'] = projected_soc_percent
        df['projected_battery_cost'] = projected_battery_cost
        df['water_from_pv_kwh'] = water_from_pv
        df['water_from_battery_kwh'] = water_from_battery
        df['water_from_grid_kwh'] = water_from_grid
        df['export_kwh'] = export_kwh
        df['export_revenue'] = export_revenue
        df['battery_charge_kw'] = battery_charge_kw_series
        df['battery_discharge_kw'] = battery_discharge_kw_series
        df['manual_action'] = manual_request_series
        df['_entry_soc_percent'] = entry_soc_percent_series
        df['_entry_soc_kwh'] = entry_soc_kwh_series
        self._last_protective_soc_kwh = protective_soc_kwh
        self._last_strategic_target_kwh = strategic_target_kwh
        self._slot_entry_soc_percent = pd.Series(entry_soc_percent_series, index=df.index)
        self._slot_entry_soc_kwh = pd.Series(entry_soc_kwh_series, index=df.index)

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
        cancelled_charge_indices: set[int] = set()

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
                        cancelled_charge_indices.add(i)

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
                        cancelled_charge_indices.add(i)

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
        if cancelled_charge_indices:
            charge_cols = [col for col in ('charge_kw', 'battery_charge_kw') if col in df.columns]
            if charge_cols:
                for idx in cancelled_charge_indices:
                    for col in charge_cols:
                        df.iat[idx, df.columns.get_loc(col)] = 0.0

        # Re-simulate the schedule with the new actions to update SoC and costs
        # This is a simplified approach - in production, we'd need to re-run the full simulation
        # For now, we'll just update the action classifications

        return df

    def _apply_soc_target_percent(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Derive the per-slot SoC target signal based on planner actions and configuration.

        Args:
            df (pd.DataFrame): Schedule dataframe after hysteresis adjustments.

        Returns:
            pd.DataFrame: DataFrame with ``soc_target_percent`` column applied.
        """
        if df is None or df.empty:
            df['soc_target_percent'] = []
            return df

        entry_series = df.get('_entry_soc_percent')
        if entry_series is None:
            df['soc_target_percent'] = df.get('projected_soc_percent', pd.Series([None] * len(df)))
            return df

        entry_list = entry_series.tolist()
        actions = df['action'].tolist() if 'action' in df else ['Hold'] * len(df)
        projected = df.get('projected_soc_percent', pd.Series([None] * len(df))).tolist()
        water_kw = df.get('water_heating_kw', pd.Series([0.0] * len(df))).tolist()
        water_from_grid = df.get('water_from_grid_kwh', pd.Series([0.0] * len(df))).tolist()
        water_from_battery = df.get('water_from_battery_kwh', pd.Series([0.0] * len(df))).tolist()
        manual_series = df.get('manual_action', pd.Series([None] * len(df)))
        manual_actions = [
            m.strip().lower() if isinstance(m, str) else None
            for m in manual_series.tolist()
        ]

        min_soc_percent = float(self.battery_config.get('min_soc_percent', 15.0))
        max_soc_percent = float(self.battery_config.get('max_soc_percent', 100.0))
        manual_cfg = getattr(self, 'manual_planning', {}) or {}
        def _clamp_manual(value: Optional[float], fallback: float) -> float:
            if value is None:
                return fallback
            try:
                val = float(value)
            except (TypeError, ValueError):
                return fallback
            return max(min_soc_percent, min(max_soc_percent, val))

        capacity_kwh = float(self.battery_config.get('capacity_kwh', 0.0))
        protective_soc_kwh = getattr(self, '_last_protective_soc_kwh', None)

        def _pct(value: Optional[float]) -> float:
            if value is None or capacity_kwh <= 0:
                return min_soc_percent
            return max(0.0, min(100.0, (value / capacity_kwh) * 100.0))

        guard_floor_percent = max(
            min_soc_percent,
            _pct(protective_soc_kwh),
        )
        # In manual mode, optionally ignore protective guard (let targets drop to min)
        ignore_guard = bool(manual_cfg.get('ignore_protective_guard', True))
        if ignore_guard and any(a is not None for a in manual_actions):
            guard_floor_percent = min_soc_percent

        manual_charge_target_percent = _clamp_manual(
            manual_cfg.get('charge_target_percent'),
            max_soc_percent,
        )
        manual_export_target_percent = _clamp_manual(
            manual_cfg.get('export_target_percent'),
            guard_floor_percent,
        )

        targets = [min_soc_percent for _ in range(len(df))]
        index_list = list(df.index)
        now_slot = getattr(self, 'now_slot', index_list[0])
        try:
            now_pos = index_list.index(now_slot)
        except ValueError:
            now_pos = -1

        # Preserve historical SoC targets using entry values
        if now_pos >= 0:
            for i in range(now_pos):
                entry = entry_list[i]
                if entry is not None:
                    targets[i] = float(entry)

        # Action-specific overrides for future slots
        start_idx = max(now_pos + 1, 0)
        for i in range(start_idx, len(df)):
            action = actions[i]
            entry = entry_list[i]
            if action == 'Hold' and entry is not None:
                targets[i] = float(entry)
            elif action == 'Export':
                if manual_actions[i] == 'export':
                    targets[i] = manual_export_target_percent
                else:
                    targets[i] = guard_floor_percent
            elif action == 'Discharge':
                targets[i] = min_soc_percent

        # Apply block-level adjustments for charge and export
        i = start_idx
        while i < len(df):
            if actions[i] == 'Charge':
                start = i
                manual_block = manual_actions[i] == 'charge'
                while i + 1 < len(df) and actions[i + 1] == 'Charge':
                    i += 1
                    if manual_actions[i] == 'charge':
                        manual_block = True
                end = i
                block_target = projected[end]
                if block_target is None:
                    block_target = projected[start]
                if block_target is None and entry_list[start] is not None:
                    block_target = entry_list[start]
                block_value = float(block_target) if block_target is not None else targets[start]
                block_value = max(min_soc_percent, min(max_soc_percent, block_value))
                if manual_block:
                    block_value = min(block_value, manual_charge_target_percent)
                for j in range(start, end + 1):
                    targets[j] = block_value
                i += 1
            else:
                i += 1

        i = start_idx
        while i < len(df):
            if actions[i] == 'Export':
                start = i
                manual_block = manual_actions[i] == 'export'
                while i + 1 < len(df) and actions[i + 1] == 'Export':
                    i += 1
                    if manual_actions[i] == 'export':
                        manual_block = True
                end = i
                block_value = manual_export_target_percent if manual_block else guard_floor_percent
                for j in range(start, end + 1):
                    targets[j] = block_value
                i += 1
            else:
                i += 1

        # Water heating blocks: differentiate battery vs grid supply
        i = start_idx
        while i < len(df):
            if water_kw[i] > 0:
                start = i
                has_battery = water_from_battery[i] > 0
                has_grid = water_from_grid[i] > 0
                while i + 1 < len(df) and water_kw[i + 1] > 0:
                    i += 1
                    has_battery = has_battery or water_from_battery[i] > 0
                    has_grid = has_grid or water_from_grid[i] > 0
                end = i
                if has_battery:
                    for j in range(start, end + 1):
                        targets[j] = min_soc_percent
                elif has_grid:
                    block_entry = entry_list[start]
                    block_value = float(block_entry) if block_entry is not None else targets[start]
                    for j in range(start, end + 1):
                        targets[j] = block_value
                i += 1
            else:
                i += 1

        df['soc_target_percent'] = [round(float(val), 4) for val in targets]

        drop_candidates = ['_entry_soc_percent', '_entry_soc_kwh', 'manual_action']
        existing = [col for col in drop_candidates if col in df.columns]
        if existing:
            df = df.drop(columns=existing)

        return df

    def _save_schedule_to_json(self, schedule_df):
        """
        Save the final schedule to schedule.json in the required format.
        Preserves past hours from existing schedule when regenerating.

        Args:
            schedule_df (pd.DataFrame): The final schedule DataFrame
        """
        # Generate new future schedule
        new_future_records = dataframe_to_json_response(schedule_df)
        
        # Add is_historical: false to new slots
        for record in new_future_records:
            record['is_historical'] = False

        # Preserve past slots from database (source of truth) with local fallback
        existing_past_slots = []
        try:
            # Load secrets for database access
            secrets_path = 'secrets.yaml'
            secrets = {}
            if os.path.exists(secrets_path):
                with open(secrets_path, 'r') as f:
                    secrets = yaml.safe_load(f) or {}
            
            # Get current time in local timezone
            tz_name = self.config.get('timezone', 'Europe/Stockholm')
            tz = pytz.timezone(tz_name)
            now = datetime.now(tz)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Use shared preservation logic (tries DB first, falls back to local)
            from db_writer import get_preserved_slots
            existing_past_slots = get_preserved_slots(today_start, now, secrets)
                        
        except Exception as e:
            print(f"[planner] Warning: Could not preserve past slots: {e}")

        # Merge: preserved past + new future (no duplicates since new_future_records only contains future slots)
        merged_schedule = existing_past_slots + new_future_records

        forecast_meta = {
            'pv_forecast_days': len(getattr(self, 'daily_pv_forecast', {}) or {}),
            'weather_forecast_days': len(getattr(self, '_last_temperature_forecast', {}) or {}),
        }
        self.forecast_meta = forecast_meta

        output = {
            'schedule': merged_schedule,
            'meta': {
                'forecast': forecast_meta
            }
        }

        # Add debug payload if enabled
        debug_config = self.config.get('debug', {})
        if debug_config.get('enable_planner_debug', False):
            debug_payload = self._generate_debug_payload(schedule_df)
            output['debug'] = debug_payload
            self._record_debug_payload(debug_payload)

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
                'total_charge_kwh': round((schedule_df.get('charge_kw', schedule_df.get('battery_charge_kw', pd.Series([0]))).sum()) * 0.25, 2),
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
            's_index': getattr(self, 's_index_debug', None),
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
    Only includes current and future slots (past slots are filtered out).
    
    Args:
        df (pd.DataFrame): The schedule DataFrame
        
    Returns:
        list: List of dictionaries ready for JSON response
    """
    df_copy = df.reset_index().copy()
    df_copy.rename(columns={'action': 'classification'}, inplace=True)

    # Filter to only current and future slots
    import pytz
    from datetime import datetime
    
    tz_name = 'Europe/Stockholm'  # Default timezone
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    
    # Filter DataFrame to only include slots from current time onwards
    df_copy = df_copy[df_copy['start_time'] >= now]
    
    records = df_copy.to_dict('records')

    for i, record in enumerate(records):
        record['slot_number'] = i + 1
        record['start_time'] = record['start_time'].isoformat()
        record['end_time'] = record['end_time'].isoformat()

        # Prefer explicit battery power fields; fallback to legacy
        if 'battery_charge_kw' not in record and 'charge_kw' in record:
            record['battery_charge_kw'] = record.get('charge_kw', 0.0)
        if 'battery_discharge_kw' not in record:
            record['battery_discharge_kw'] = 0.0

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

        # Add is_historical flag for preserved past slots (default to False for new slots)
        record['is_historical'] = record.get('is_historical', False)

        for key, value in record.items():
            if isinstance(value, float):
                # Round SOC values to whole numbers (as integers), other values to 2 decimals
                if 'soc' in key.lower():
                    record[key] = int(round(value, 0))
                else:
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
    temp_planner.manual_planning = config.get('manual_planning', {}) or {}
    temp_planner.learning_config = config.get('learning', {})
    temp_planner._learning_schema_initialized = False
    temp_planner.daily_pv_forecast = {}
    temp_planner.daily_load_forecast = {}
    temp_planner._last_temperature_forecast = {}
    temp_planner.forecast_meta = {}
    temp_planner._validate_config()

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
    
    # Run the simulation pass and apply SoC targets
    simulated_df = temp_planner._pass_6_finalize_schedule(df)
    simulated_df = temp_planner._apply_soc_target_percent(simulated_df)
    return simulated_df


if __name__ == "__main__":
    input_data = get_all_input_data()
    planner = HeliosPlanner("config.yaml")
    df = planner.generate_schedule(input_data)
    print("Successfully generated and saved schedule to schedule.json")
