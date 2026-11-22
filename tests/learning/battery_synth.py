"""Synthetic slot rows from a known DC battery behind an inverter (test helper)."""

import json
import random
from datetime import date, datetime, timedelta
from collections.abc import Callable
from typing import Any

import pytz

from backend.measurement_provenance import ENERGY_SEMANTICS, PROVENANCE_SCHEMA_VERSION

TZ = pytz.timezone("Europe/Stockholm")
CAPACITY_KWH = 30.0
SLOTS_PER_DAY = 96
SLOT_HOURS = 0.25
FIRST_DAY = date(2026, 1, 5)


def flags(extra: dict[str, Any] | None = None, *, battery_method: str = "power_history") -> str:
    def component(method: str = "power_history") -> dict[str, str]:
        return {"method": method, "owner": "recorder"}

    value: dict[str, Any] = {
        "recording": {
            "schema_version": PROVENANCE_SCHEMA_VERSION,
            "semantics": ENERGY_SEMANTICS,
            "boundary_fingerprint": "a" * 64,
            "components": {
                "pv": component(),
                "import": component(),
                "export": component(),
                "load": component(),
                "battery_charge": component(battery_method),
                "battery_discharge": component(battery_method),
                "water": component("disabled_zero"),
                "ev": component("disabled_zero"),
            },
            "soc": {"source": "live", "owner": "recorder", "end": {"source": "live"}},
        }
    }
    value.update(extra or {})
    return json.dumps(value)


def iso(day: date, slot: int) -> tuple[str, str]:
    start = TZ.localize(datetime.combine(day, datetime.min.time()) + timedelta(minutes=15 * slot))
    return start.isoformat(), (start + timedelta(minutes=15)).isoformat()


def make_rows(
    days: int,
    *,
    first_day: date = FIRST_DAY,
    rte: float = 0.962,
    charge_loss_k: float = 0.075,
    standby_w: float = 60.0,
    noise_kwh: float = 0.004,
    outlier_share: float = 0.0,
    seed: int = 7,
    daily_charge_kwh: float = 12.0,
    start_soc: float = 30.0,
    discharge_scale_for_day: Callable[[int], float] | None = None,
) -> list[dict[str, Any]]:
    """Rows of a battery that cycles daily; it ends every day at the same SoC by default.

    ``discharge_scale_for_day`` scales the day's discharge against the neutral amount
    (``charge x rte``), so the SoC drifts up (< 1) or down (> 1) on that day.

    DC counters follow ``stored += charge x sqrt(rte) - discharge / sqrt(rte)``; the energy
    balance residual is ``standby x hours + k x DC charge`` plus noise.
    """
    rng = random.Random(seed)
    root = rte**0.5
    rows: list[dict[str, Any]] = []
    stored = start_soc / 100.0 * CAPACITY_KWH
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        weights_c = [rng.uniform(0.2, 1.0) for _ in range(24)]
        weights_d = [rng.uniform(0.2, 1.0) for _ in range(20)]
        charge = {32 + i: daily_charge_kwh * w / sum(weights_c) for i, w in enumerate(weights_c)}
        scale = discharge_scale_for_day(offset) if discharge_scale_for_day else 1.0
        discharge_total = daily_charge_kwh * rte * scale
        discharge = {68 + i: discharge_total * w / sum(weights_d) for i, w in enumerate(weights_d)}
        for slot in range(SLOTS_PER_DAY):
            dc_charge = charge.get(slot, 0.0)
            dc_discharge = discharge.get(slot, 0.0)
            stored += dc_charge * root - dc_discharge / root
            load = rng.uniform(0.1, 0.4)
            pv = rng.uniform(0.0, 0.3) if 40 <= slot < 70 else 0.0
            loss = standby_w / 1000.0 * SLOT_HOURS + charge_loss_k * dc_charge
            loss += rng.gauss(0.0, noise_kwh)
            if rng.random() < outlier_share:
                loss += rng.choice([-1.0, 1.0]) * rng.uniform(0.5, 1.5)
            grid = load + dc_charge + loss - pv - dc_discharge
            start, end = iso(day, slot)
            rows.append(
                {
                    "slot_start": start,
                    "slot_end": end,
                    "import_kwh": max(grid, 0.0),
                    "export_kwh": max(-grid, 0.0),
                    "pv_kwh": pv,
                    "load_kwh": load,
                    "water_kwh": 0.0,
                    "ev_charging_kwh": 0.0,
                    "batt_charge_kwh": dc_charge,
                    "batt_discharge_kwh": dc_discharge,
                    "soc_end_percent": stored / CAPACITY_KWH * 100.0,
                    "quality_flags": flags(),
                }
            )
    return rows


def after(days: int, first_day: date = FIRST_DAY) -> datetime:
    """Local midnight ``days`` after ``first_day`` (an ``as_of`` right after the data)."""
    return TZ.localize(datetime.combine(first_day + timedelta(days=days), datetime.min.time()))


def capacity_rows(
    days: int,
    capacity_for_day: Any,
    *,
    first_day: date = FIRST_DAY,
    daily_kwh: float = 10.0,
    start_stored_kwh: float = 5.0,
) -> list[dict[str, Any]]:
    """Rows of a lossless battery whose meter flows give SoC = stored / capacity.

    Charges ``daily_kwh`` in 12 morning slots and discharges the same in 12 evening slots;
    the capacity (kWh) of day ``i`` is ``capacity_for_day(i)``.
    """
    rows: list[dict[str, Any]] = []
    stored = start_stored_kwh
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        capacity = float(capacity_for_day(offset))
        scale = 1.0 + 0.15 * ((offset * 7) % 5 - 2) / 2  # varied swing keeps the fit conditioned
        for slot in range(SLOTS_PER_DAY):
            charge = daily_kwh * scale / 12 if 32 <= slot < 44 else 0.0
            discharge = daily_kwh * scale / 12 if 68 <= slot < 80 else 0.0
            stored += charge - discharge
            start, end = iso(day, slot)
            rows.append(
                {
                    "slot_start": start,
                    "slot_end": end,
                    "import_kwh": charge,
                    "export_kwh": discharge,
                    "pv_kwh": 0.0,
                    "load_kwh": 0.0,
                    "water_kwh": 0.0,
                    "ev_charging_kwh": 0.0,
                    "batt_charge_kwh": charge,
                    "batt_discharge_kwh": discharge,
                    "soc_end_percent": stored / capacity * 100.0,
                    "quality_flags": flags(),
                }
            )
    return rows


def make_ac_battery_rows(
    days: int,
    *,
    first_day: date = FIRST_DAY,
    rte: float = 0.962,
    charge_loss_ac: float = 0.07,
    discharge_eff: float = 0.97,
    standby_w: float = 60.0,
    seed: int = 11,
    daily_dc_charge_kwh: float = 12.0,
    start_soc: float = 30.0,
) -> list[dict[str, Any]]:
    """Rows from a DC battery behind an inverter with AC-side losses (evaluation truth).

    AC charge ``a`` stores ``a x (1 - charge_loss_ac) x sqrt(rte)``; discharging ``d`` (DC)
    delivers ``d x discharge_eff`` AC and removes ``d / sqrt(rte)`` from storage. DC counters
    carry the battery-terminal flows; the grid balance carries the AC flows plus standby.
    """
    rng = random.Random(seed)
    root = rte**0.5
    stored = start_soc / 100.0 * CAPACITY_KWH
    rows: list[dict[str, Any]] = []
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        weights_c = [rng.uniform(0.3, 1.0) for _ in range(24)]
        weights_d = [rng.uniform(0.3, 1.0) for _ in range(12)]
        ac_total = daily_dc_charge_kwh / (1.0 - charge_loss_ac)
        dc_dis_total = daily_dc_charge_kwh * rte
        for slot in range(SLOTS_PER_DAY):
            ac_charge = ac_total * weights_c[slot - 32] / sum(weights_c) if 32 <= slot < 56 else 0.0
            dc_discharge = (
                dc_dis_total * weights_d[slot - 68] / sum(weights_d) if 68 <= slot < 80 else 0.0
            )
            dc_charge = ac_charge * (1.0 - charge_loss_ac)
            ac_discharge = dc_discharge * discharge_eff
            stored += dc_charge * root - dc_discharge / root
            load = rng.uniform(0.1, 0.3)
            grid = load + ac_charge - ac_discharge + standby_w / 1000.0 * SLOT_HOURS
            start, end = iso(day, slot)
            rows.append(
                {
                    "slot_start": start,
                    "slot_end": end,
                    "import_kwh": max(grid, 0.0),
                    "export_kwh": max(-grid, 0.0),
                    "pv_kwh": 0.0,
                    "load_kwh": load,
                    "water_kwh": 0.0,
                    "ev_charging_kwh": 0.0,
                    "batt_charge_kwh": dc_charge,
                    "batt_discharge_kwh": dc_discharge,
                    "soc_end_percent": stored / CAPACITY_KWH * 100.0,
                    "quality_flags": flags(),
                }
            )
    return rows
