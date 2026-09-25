"""Pre-flight validator that runs before the Kepler solver.

Raises PlannerError on blocking failures; logs warnings for non-blocking conditions.
Checks run in a fixed order: battery config → initial SoC → SoC staleness →
EV chargers → EV deadlines → price data → forecast data → numeric sanity.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.core.ev_power import charger_max_kw, nominal_voltage_v

from .errors import PlannerError, PlannerErrorCode, user_message

logger = logging.getLogger("darkstar.planner.preflight")

SOC_STALENESS_WARNING_MINUTES = 30
PRICE_HORIZON_MIN_HOURS = 4


def check_battery_config(config: dict[str, Any]) -> None:
    system = config.get("system", {})
    battery_enabled = system.get("has_battery", True)
    battery = config.get("battery", {})

    min_pct = battery.get("min_soc_percent", 0.0)
    max_pct = battery.get("max_soc_percent", 100.0)
    capacity = battery.get("capacity_kwh", 0.0)
    max_charge = battery.get("max_charge_w", 0.0) / 1000
    max_discharge = battery.get("max_discharge_w", 0.0) / 1000

    if min_pct >= max_pct:
        raise PlannerError(
            code=PlannerErrorCode.CONFIG_INVALID,
            details={
                "field": "min_soc_percent/max_soc_percent",
                "min_soc_percent": min_pct,
                "max_soc_percent": max_pct,
            },
        )

    if battery_enabled:
        if capacity <= 0:
            raise PlannerError(
                code=PlannerErrorCode.CONFIG_INVALID,
                details={"field": "battery.capacity_kwh", "value": capacity},
            )
        if max_charge <= 0:
            raise PlannerError(
                code=PlannerErrorCode.CONFIG_INVALID,
                details={"field": "battery.max_charge_w", "value": max_charge},
            )
        if max_discharge <= 0:
            raise PlannerError(
                code=PlannerErrorCode.CONFIG_INVALID,
                details={"field": "battery.max_discharge_w", "value": max_discharge},
            )


def check_initial_soc(input_data: dict[str, Any], config: dict[str, Any]) -> None:
    initial_state = input_data.get("initial_state", {})
    capacity = float(config.get("battery", {}).get("capacity_kwh", 0.0))
    initial_soc_kwh = float(
        initial_state.get("battery_kwh", initial_state.get("battery_soc_kwh", 0.0))
    )
    if initial_soc_kwh == 0.0 and "battery_soc_percent" in initial_state:
        initial_soc_kwh = float(initial_state["battery_soc_percent"]) / 100.0 * capacity

    if initial_soc_kwh < 0 or initial_soc_kwh > capacity:
        raise PlannerError(
            code=PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE,
            details={"initial_soc_kwh": initial_soc_kwh, "capacity_kwh": capacity},
        )


def check_soc_staleness(input_data: dict[str, Any]) -> None:
    initial_state = input_data.get("initial_state", {})
    soc_timestamp_raw = initial_state.get("soc_timestamp")
    if soc_timestamp_raw is None:
        return  # Timestamp not available — skip check

    try:
        if isinstance(soc_timestamp_raw, datetime):
            soc_ts = soc_timestamp_raw
        else:
            soc_ts = datetime.fromisoformat(str(soc_timestamp_raw))

        if soc_ts.tzinfo is None:
            soc_ts = soc_ts.replace(tzinfo=UTC)

        age_minutes = (datetime.now(UTC) - soc_ts).total_seconds() / 60.0

        if age_minutes > SOC_STALENESS_WARNING_MINUTES:
            logger.warning(
                "DATA_STALE: SoC reading is %.0f minutes old (threshold: %d min). %s",
                age_minutes,
                SOC_STALENESS_WARNING_MINUTES,
                user_message(PlannerErrorCode.DATA_STALE),
            )
    except Exception as e:
        logger.debug("Could not parse soc_timestamp for staleness check: %s", e)


def check_ev_chargers(config: dict[str, Any]) -> None:
    ev_chargers = config.get("ev_chargers", [])
    voltage = nominal_voltage_v(config)
    for ev in ev_chargers:
        if not ev.get("enabled", True):
            continue
        charger_id = ev.get("id", "<unknown>")
        max_kw = charger_max_kw(ev, voltage)
        if max_kw <= 0:
            control_type = str(ev.get("type", "binary") or "binary").lower()
            details: dict[str, Any] = {"charger_id": charger_id, "type": control_type}
            if control_type == "current":
                details["max_current_a"] = ev.get("max_current_a")
                details["phases"] = ev.get("phases")
            else:
                details["rated_power_kw"] = ev.get("rated_power_kw")
            raise PlannerError(code=PlannerErrorCode.EV_MISSING_POWER, details=details)
        capacity = ev.get("battery_capacity_kwh", 0.0) or 0.0
        if capacity <= 0:
            raise PlannerError(
                code=PlannerErrorCode.EV_INVALID_CAPACITY,
                details={"charger_id": charger_id, "battery_capacity_kwh": capacity},
            )


def check_ev_deadlines(config: dict[str, Any], now: datetime) -> None:
    ev_chargers = config.get("ev_chargers", [])
    for ev in ev_chargers:
        if not ev.get("enabled", True):
            continue
        charger_id = ev.get("id", "<unknown>")
        deadline_raw = ev.get("deadline")
        if deadline_raw is None:
            continue
        try:
            if isinstance(deadline_raw, datetime):
                deadline = deadline_raw
            else:
                deadline = datetime.fromisoformat(str(deadline_raw))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=now.tzinfo or UTC)
            if deadline < now:
                logger.warning(
                    "EV_DEADLINE_PAST: Charger %s deadline %s is before now (%s). %s",
                    charger_id,
                    deadline.isoformat(),
                    now.isoformat(),
                    user_message(PlannerErrorCode.EV_DEADLINE_PAST),
                )
        except Exception as e:
            logger.debug("Could not parse EV deadline for charger %s: %s", charger_id, e)


def check_price_data(input_data: dict[str, Any], now: datetime) -> None:
    price_data: list[dict[str, Any]] = input_data.get("price_data") or []

    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    future_slots: list[datetime] = []
    for slot in price_data:
        try:
            start_raw = slot.get("start_time")
            if start_raw is None:
                continue
            if isinstance(start_raw, datetime):
                start = start_raw
            else:
                start = datetime.fromisoformat(str(start_raw))
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if start >= now:
                future_slots.append(start)
        except Exception:
            continue

    if not future_slots:
        raise PlannerError(
            code=PlannerErrorCode.PRICES_UNAVAILABLE,
            details={"price_slot_count": 0, "min_required_hours": PRICE_HORIZON_MIN_HOURS},
        )

    min_start: datetime = min(future_slots)
    max_start: datetime = max(future_slots)
    horizon_hours: float = (max_start - min_start).total_seconds() / 3600.0 + 0.25  # +1 slot width

    if horizon_hours < PRICE_HORIZON_MIN_HOURS:
        raise PlannerError(
            code=PlannerErrorCode.PRICES_UNAVAILABLE,
            details={
                "observed_horizon_hours": round(horizon_hours, 2),
                "min_required_hours": PRICE_HORIZON_MIN_HOURS,
                "first_slot": min_start.isoformat(),
                "last_slot": max_start.isoformat(),
            },
        )


def check_forecast_data(input_data: dict[str, Any]) -> None:
    forecast_data: list[dict[str, Any]] = input_data.get("forecast_data") or []
    price_data: list[dict[str, Any]] = input_data.get("price_data") or []

    if not forecast_data:
        raise PlannerError(
            code=PlannerErrorCode.FORECAST_UNAVAILABLE,
            details={"forecast_slot_count": 0},
        )

    forecast_starts: list[datetime] = []
    for slot in forecast_data:
        start_raw = slot.get("start_time")
        if start_raw is None:
            continue
        try:
            if isinstance(start_raw, datetime):
                start = start_raw
            else:
                start = datetime.fromisoformat(str(start_raw))
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            forecast_starts.append(start)
        except Exception:
            continue

    if not forecast_starts:
        raise PlannerError(
            code=PlannerErrorCode.FORECAST_UNAVAILABLE,
            details={"forecast_slot_count": 0},
        )

    forecast_min: datetime = min(forecast_starts)
    forecast_max: datetime = max(forecast_starts)

    # Check coverage against price horizon (if price data available)
    price_ends: list[datetime] = []
    for slot in price_data:
        end_raw = slot.get("end_time") or slot.get("start_time")
        if end_raw is None:
            continue
        try:
            end = end_raw if isinstance(end_raw, datetime) else datetime.fromisoformat(str(end_raw))
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            price_ends.append(end)
        except Exception:
            continue

    if price_ends:
        price_horizon_end: datetime = max(price_ends)
        if forecast_max < price_horizon_end - timedelta(hours=1):
            raise PlannerError(
                code=PlannerErrorCode.FORECAST_UNAVAILABLE,
                details={
                    "forecast_horizon_start": forecast_min.isoformat(),
                    "forecast_horizon_end": forecast_max.isoformat(),
                    "price_horizon_end": price_horizon_end.isoformat(),
                },
            )


def check_numeric_sanity(input_data: dict[str, Any]) -> None:
    price_data: list[dict[str, Any]] = input_data.get("price_data") or []
    forecast_data: list[dict[str, Any]] = input_data.get("forecast_data") or []

    price_fields = ["import_price_sek_kwh", "export_price_sek_kwh"]
    for i, slot in enumerate(price_data):
        for field in price_fields:
            val = slot.get(field)
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if math.isnan(fval) or math.isinf(fval):
                raise PlannerError(
                    code=PlannerErrorCode.NUMERIC_INVALID,
                    details={"field": f"price_data[{i}].{field}", "slot_index": i, "value": val},
                )

    forecast_fields = ["pv_forecast_kwh", "load_forecast_kwh"]
    for i, slot in enumerate(forecast_data):
        for field in forecast_fields:
            val = slot.get(field)
            if val is None:
                continue
            try:
                fval = float(val)
            except (TypeError, ValueError):
                continue
            if math.isnan(fval) or math.isinf(fval):
                raise PlannerError(
                    code=PlannerErrorCode.NUMERIC_INVALID,
                    details={
                        "field": f"forecast_data[{i}].{field}",
                        "slot_index": i,
                        "value": val,
                    },
                )


def run_preflight(input_data: dict[str, Any], config: dict[str, Any]) -> None:
    """Run all pre-flight checks before the Kepler solve step.

    Blocking checks raise PlannerError on first failure.
    Warning-only checks log and continue.
    """
    now = datetime.now(UTC)

    # Blocking checks (raise on first failure)
    check_battery_config(config)
    check_initial_soc(input_data, config)

    # Warning-only (log and continue)
    check_soc_staleness(input_data)

    # Blocking checks continued
    check_ev_chargers(config)

    # Warning-only
    check_ev_deadlines(config, now)

    # Blocking checks continued
    check_price_data(input_data, now)
    check_forecast_data(input_data)
    check_numeric_sanity(input_data)
