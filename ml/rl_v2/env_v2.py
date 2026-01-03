"""Sequence-based Antares RL v2 environment (Rev 84).

This environment is used only inside the RL v2 lab. It replays a single
historical day using `SimulationDataLoader` and exposes a sequence-based
state as described in `ml/rl_v2/contract.py`.

The dynamics are simple but physically consistent:
    - Exogenous inputs per slot: realised load, PV and prices.
    - Actions: battery charge/discharge power in kW (export is derived).
    - Battery SoC is updated from charge/discharge subject to capacity and
      min/max SoC.
    - Grid import/export are computed from an energy balance where PV and
      discharge are used to cover load and charging before exporting.

Reward is the negative slot cost:
    cost = grid_import * import_price
           - grid_export * export_price
           + wear_cost * (charge_kwh + discharge_kwh)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date_cls, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from ml.rl_v2.contract import RlV2StateSpec
from ml.simulation.data_loader import SimulationDataLoader


@dataclass
class RlV2StepResult:
    """One step transition for the RL v2 env."""

    next_state: np.ndarray
    reward: float
    done: bool
    info: dict[str, Any]


class AntaresEnvV2:
    """Sequence-based RL v2 environment for a single historical day."""

    def __init__(self, config_path: str = "config.yaml", seq_len: int = 48) -> None:
        self.config_path = config_path
        self.loader = SimulationDataLoader(config_path=config_path)
        self.timezone = self.loader.timezone

        cfg = self.loader.config
        system_cfg = cfg.get("system", {}) or {}
        battery_cfg = system_cfg.get("battery", {}) or {}
        learning_cfg = cfg.get("learning", {}) or {}

        self._capacity_kwh: float = float(
            battery_cfg.get("capacity_kwh", self.loader.battery_capacity_kwh)
        )
        self._min_soc_percent: float = float(battery_cfg.get("min_soc_percent", 10.0))
        self._max_soc_percent: float = float(battery_cfg.get("max_soc_percent", 100.0))
        self._max_charge_power_kw: float = float(battery_cfg.get("max_charge_power_kw", 3.0))
        self._max_discharge_power_kw: float = float(battery_cfg.get("max_discharge_power_kw", 3.0))
        self._wear_cost_sek_per_kwh: float = float(
            learning_cfg.get(
                "default_battery_cost_sek_per_kwh",
                self.loader.battery_cost,
            )
        )

        self._state_spec = RlV2StateSpec(seq_len=seq_len)

        self._day: _date_cls | None = None
        self._df: pd.DataFrame | None = None
        self._current_idx: int = 0

        self._soc_kwh: float = 0.0
        self._min_soc_kwh: float = 0.0
        self._max_soc_kwh: float = 0.0
        self._initial_soc_percent: float = 0.0
        # Terminal SoC penalty: SEK per percentage point deviation from start.
        # This is intentionally non-trivial to discourage large SoC drift
        # across a single simulated day when comparing policies.
        self._terminal_soc_penalty_per_pct: float = 2.0

    def _normalize_day(self, day: Any) -> _date_cls:
        if isinstance(day, _date_cls) and not isinstance(day, datetime):
            return day
        if isinstance(day, datetime):
            return day.date()
        if isinstance(day, str):
            return datetime.fromisoformat(day).date()
        raise TypeError(f"Unsupported day type for AntaresEnvV2: {type(day)}")

    def _load_day_frame(self, target_day: _date_cls) -> pd.DataFrame:
        tz = self.timezone
        start_dt = tz.localize(datetime.combine(target_day, datetime.min.time()))
        end_dt = start_dt + timedelta(days=1)

        query = """
            SELECT
                slot_start,
                slot_end,
                load_kwh,
                pv_kwh,
                import_price_sek_kwh,
                export_price_sek_kwh
            FROM slot_observations
            WHERE slot_start >= ? AND slot_start < ?
            ORDER BY slot_start ASC
        """
        with sqlite3.connect(self.loader.db_path, timeout=30.0) as conn:
            df = pd.read_sql_query(
                query,
                conn,
                params=(start_dt.isoformat(), end_dt.isoformat()),
            )

        if df.empty:
            raise RuntimeError(f"No slot_observations rows for day {target_day}")

        df["slot_start"] = pd.to_datetime(df["slot_start"], utc=True, errors="coerce")
        df["slot_end"] = pd.to_datetime(df["slot_end"], utc=True, errors="coerce")
        df = df.dropna(subset=["slot_start", "slot_end"])
        if df.empty:
            raise RuntimeError(f"No valid slot timestamps for day {target_day}")

        df["slot_start"] = df["slot_start"].dt.tz_convert(tz)
        df["slot_end"] = df["slot_end"].dt.tz_convert(tz)

        df["load_kwh"] = pd.to_numeric(df["load_kwh"], errors="coerce").fillna(0.0)
        df["pv_kwh"] = pd.to_numeric(df["pv_kwh"], errors="coerce").fillna(0.0)
        df["import_price_sek_kwh"] = pd.to_numeric(
            df["import_price_sek_kwh"], errors="coerce"
        ).fillna(0.0)
        df["export_price_sek_kwh"] = pd.to_numeric(df["export_price_sek_kwh"], errors="coerce")
        df["export_price_sek_kwh"] = df["export_price_sek_kwh"].fillna(df["import_price_sek_kwh"])

        slot_hours = (df["slot_end"] - df["slot_start"]).dt.total_seconds() / 3600.0
        df["slot_hours"] = slot_hours.fillna(0.25).clip(lower=0.01)

        df["hour_of_day"] = df["slot_start"].dt.hour + df["slot_start"].dt.minute / 60.0

        return df.reset_index(drop=True)

    def reset(self, day: Any) -> np.ndarray:
        """Reset the environment to the start of the given day."""
        target_day = self._normalize_day(day)
        self._day = target_day
        self._df = self._load_day_frame(target_day)
        self._current_idx = 0

        start_dt = self.timezone.localize(datetime.combine(target_day, datetime.min.time()))
        initial = self.loader.get_initial_state_from_history(start_dt)
        self._soc_kwh = float(initial.get("battery_kwh", 0.0) or 0.0)
        self._min_soc_kwh = self._capacity_kwh * self._min_soc_percent / 100.0
        self._max_soc_kwh = self._capacity_kwh * self._max_soc_percent / 100.0
        self._soc_kwh = min(
            max(self._soc_kwh, self._min_soc_kwh),
            self._max_soc_kwh,
        )

        if self._capacity_kwh > 0.0:
            self._initial_soc_percent = 100.0 * self._soc_kwh / self._capacity_kwh
        else:
            self._initial_soc_percent = 0.0

        return self._build_state_vector(self._current_idx)

    def _build_state_vector(self, idx: int) -> np.ndarray:
        if self._df is None:
            raise RuntimeError("AntaresEnvV2.reset() must be called before step().")
        df = self._df
        spec = self._state_spec
        seq_len = spec.seq_len
        t_max = len(df) - 1

        row = df.iloc[idx]
        if self._capacity_kwh > 0.0:
            soc_percent = 100.0 * self._soc_kwh / self._capacity_kwh
        else:
            soc_percent = 0.0
        hour_of_day = float(row["hour_of_day"])

        prices = df["import_price_sek_kwh"].to_numpy(dtype=np.float32)
        net_load_kwh = (df["load_kwh"] - df["pv_kwh"]).to_numpy(dtype=np.float32)
        slot_hours = df["slot_hours"].to_numpy(dtype=np.float32)
        slot_hours = np.where(slot_hours <= 0.0, 0.25, slot_hours)
        net_load_kw = net_load_kwh / slot_hours

        price_seq = np.empty(seq_len, dtype=np.float32)
        net_load_seq = np.empty(seq_len, dtype=np.float32)
        for offset in range(seq_len):
            j = idx + offset
            if j > t_max:
                j = t_max
            price_seq[offset] = float(prices[j])
            net_load_seq[offset] = float(net_load_kw[j])

        state = np.empty(spec.flat_dim, dtype=np.float32)
        state[0] = float(soc_percent)
        state[1] = float(hour_of_day)
        state[2 : 2 + seq_len] = price_seq
        state[2 + seq_len :] = net_load_seq
        return state

    def step(self, action: dict[str, float] | None) -> RlV2StepResult:
        """Advance one slot using the requested battery actions."""
        if self._df is None or self._day is None:
            raise RuntimeError("AntaresEnvV2.reset() must be called before step().")
        if self._current_idx >= len(self._df):
            raise RuntimeError("Episode already finished.")

        df = self._df
        idx = self._current_idx
        row = df.iloc[idx]

        slot_hours = float(row["slot_hours"]) or 0.25
        load_kwh = float(row["load_kwh"] or 0.0)
        pv_kwh = float(row["pv_kwh"] or 0.0)
        imp_price = float(row["import_price_sek_kwh"] or 0.0)
        exp_price = float(row["export_price_sek_kwh"] or imp_price)

        if action is None:
            action = {}

        charge_kw = max(0.0, float(action.get("battery_charge_kw", 0.0) or 0.0))
        discharge_kw = max(0.0, float(action.get("battery_discharge_kw", 0.0) or 0.0))

        charge_kw = min(charge_kw, self._max_charge_power_kw)
        discharge_kw = min(discharge_kw, self._max_discharge_power_kw)

        charge_kwh = charge_kw * slot_hours
        discharge_kwh = discharge_kw * slot_hours

        if self._capacity_kwh > 0.0:
            max_charge_by_soc = max(
                0.0,
                self._max_soc_kwh - self._soc_kwh,
            )
            max_discharge_by_soc = max(
                0.0,
                self._soc_kwh - self._min_soc_kwh,
            )
            charge_kwh = min(charge_kwh, max_charge_by_soc)
            discharge_kwh = min(discharge_kwh, max_discharge_by_soc)

        if slot_hours > 0.0:
            charge_kw = charge_kwh / slot_hours
            discharge_kw = discharge_kwh / slot_hours
        else:
            charge_kw = 0.0
            discharge_kw = 0.0

        self._soc_kwh = self._soc_kwh + charge_kwh - discharge_kwh
        self._soc_kwh = min(max(self._soc_kwh, self._min_soc_kwh), self._max_soc_kwh)

        used_pv_for_load = min(pv_kwh, load_kwh)
        pv_surplus = pv_kwh - used_pv_for_load
        load_residual = load_kwh - used_pv_for_load

        used_discharge_for_load = min(discharge_kwh, load_residual)
        load_residual -= used_discharge_for_load
        discharge_surplus = discharge_kwh - used_discharge_for_load

        used_pv_for_charge = min(pv_surplus, charge_kwh)
        pv_surplus -= used_pv_for_charge
        charge_residual = charge_kwh - used_pv_for_charge

        grid_import_kwh = max(0.0, load_residual + charge_residual)
        grid_export_kwh = max(0.0, pv_surplus + discharge_surplus)

        wear_kwh = charge_kwh + discharge_kwh
        slot_cost = (
            grid_import_kwh * imp_price
            - grid_export_kwh * exp_price
            + wear_kwh * self._wear_cost_sek_per_kwh
        )
        reward = -float(slot_cost)

        self._current_idx += 1
        done = self._current_idx >= len(df)
        if done:
            next_state = self._build_state_vector(len(df) - 1)
        else:
            next_state = self._build_state_vector(self._current_idx)

        if self._capacity_kwh > 0.0:
            soc_percent = 100.0 * self._soc_kwh / self._capacity_kwh
        else:
            soc_percent = 0.0

        # Apply terminal SoC shaping: penalise deviation from starting SoC.
        terminal_penalty = 0.0
        if done:
            diff_pct = abs(soc_percent - self._initial_soc_percent)
            terminal_penalty = self._terminal_soc_penalty_per_pct * diff_pct
            reward -= terminal_penalty
            slot_cost += terminal_penalty

        info: dict[str, Any] = {
            "day": self._day.isoformat(),
            "index": idx,
            "done": done,
            "slot_hours": slot_hours,
            "load_kwh": load_kwh,
            "pv_kwh": pv_kwh,
            "grid_import_kwh": grid_import_kwh,
            "grid_export_kwh": grid_export_kwh,
            "battery_charge_kwh": charge_kwh,
            "battery_discharge_kwh": discharge_kwh,
            "battery_charge_kw": charge_kw,
            "battery_discharge_kw": discharge_kw,
            "soc_kwh": self._soc_kwh,
            "soc_percent": soc_percent,
            "initial_soc_percent": self._initial_soc_percent,
            "terminal_soc_penalty_sek": terminal_penalty,
            "import_price_sek_kwh": imp_price,
            "export_price_sek_kwh": exp_price,
            "slot_cost_sek": slot_cost,
        }
        return RlV2StepResult(
            next_state=next_state,
            reward=reward,
            done=done,
            info=info,
        )
