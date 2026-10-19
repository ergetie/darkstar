"""Slot observation recorder.

Column ownership for ``slot_observations``:

| Owner | Columns | Meaning |
| --- | --- | --- |
| Recorder | energy columns, price columns | Slot-aligned measurements; ``load_kwh`` is base load after EV/water subtraction. |
| Executor | ``executed_action`` | Action summary for the slot, keyed by ``slot_start``. |

No column is intentionally written by both owners.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytz
import yaml

from backend.core.ha_client import (
    _state_timestamp,  # type: ignore[reportPrivateUsage]
    gather_sensor_reads,
    get_ha_sensor_float,
    get_ha_sensor_kw_normalized,
    get_power_history_batch,
    parse_power_states,
)
from backend.core.prices import get_current_slot_prices
from backend.core.slot_energy import build_slot_sources, compute_slot_energy, isolate_base_load
from backend.core.water_heating import (
    DEFAULT_IDLE_POWER_THRESHOLD_KW,
    WATER_HEATER_ENERGY_SCHEMA_VERSION,
    WATER_HEATER_ENERGY_SEMANTICS,
    active_water_heaters,
    normalize_active_power_kw,
)
from backend.learning.backfill import BackfillEngine

# Local imports
from backend.learning.store import LearningStore
from backend.loads.service import LoadDisaggregator
from backend.measurement_provenance import recording_metadata
from backend.validation import get_max_energy_per_slot, validate_energy_values

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("recorder")


def _load_config() -> dict[str, Any]:
    try:
        with Path("config.yaml").open(encoding="utf-8") as f:
            result: Any = yaml.safe_load(f)
            if isinstance(result, dict):
                return result  # type: ignore[return-value]
            return {}
    except FileNotFoundError:
        return {}


def _numeric_states(states: list[dict[str, Any]]) -> list[tuple[datetime, float | None]]:
    """Time-sorted ``(timestamp, value)`` of HA history states; non-numeric states map to None."""
    out: list[tuple[datetime, float | None]] = []
    for state in states:
        ts = _state_timestamp(state)
        if ts is None:
            continue
        try:
            value: float | None = float(state.get("state", ""))
        except (TypeError, ValueError):
            value = None
        out.append((ts, value))
    out.sort(key=lambda item: item[0])
    return out


DEFAULT_ENERGY_ADDED_RESET_THRESHOLD_KWH = 0.5
_WALLBOX_NEAR_ZERO_KWH = 0.01
_CAR_ENERGY_MIN_TOLERANCE_KWH = 0.05
_CAR_ENERGY_TOLERANCE_FRACTION = 0.05


def car_energy_from_added_sensor(
    states: list[dict[str, Any]],
    reset_threshold_kwh: float = DEFAULT_ENERGY_ADDED_RESET_THRESHOLD_KWH,
) -> float | None:
    """Energy-added sensor change over the slot. A drop is a session reset (the
    post-reset value counts from zero) only when the new value is at or below
    ``reset_threshold_kwh``; any other drop is sensor drift and contributes 0.
    None when the slot has no numeric reading."""
    values = [v for _, v in _numeric_states(states) if v is not None]
    if not values:
        return None
    total = 0.0
    for prev, cur in pairwise(values):
        if cur >= prev:
            total += cur - prev
        elif cur <= reset_threshold_kwh:
            total += cur
    return total


def cap_car_energy(car_kwh: float, wallbox_kwh: float) -> float:
    """Car-side energy cannot exceed grid-side energy: cap at wallbox energy plus a
    tolerance (sensor granularity, slot skew); 0 when the wallbox was idle."""
    if wallbox_kwh <= _WALLBOX_NEAR_ZERO_KWH:
        return 0.0
    tolerance = max(_CAR_ENERGY_MIN_TOLERANCE_KWH, _CAR_ENERGY_TOLERANCE_FRACTION * wallbox_kwh)
    return min(car_kwh, wallbox_kwh + tolerance)


def car_energy_from_soc(
    states: list[dict[str, Any]],
    capacity_kwh: float,
    slot_start: datetime,
    slot_end: datetime,
    stale_after_minutes: float,
) -> float | None:
    """``ΔSoC / 100 x capacity`` over the slot, only when SoC is fresh at both ends:
    the first and last readings are numeric and within ``stale_after_minutes`` of
    the slot start and end. None otherwise."""
    points = _numeric_states(states)
    if not points or capacity_kwh <= 0:
        return None
    window = timedelta(minutes=stale_after_minutes)
    (first_ts, first), (last_ts, last) = points[0], points[-1]
    if first is None or last is None:
        return None
    if first_ts > slot_start + window or last_ts < slot_end - window:
        return None
    return max(0.0, (last - first) / 100.0 * capacity_kwh)


def zero_rejected_ev_energy(record: dict[str, Any]) -> dict[str, Any]:
    """Keep per-charger wallbox and car energy consistent with a rejected (zeroed)
    aggregate ``ev_charging_kwh``."""
    if record.get("ev_charger_energy") and not record.get("ev_charging_kwh"):
        record["ev_charger_energy"] = dict.fromkeys(record["ev_charger_energy"], 0.0)
        if record.get("ev_charger_car_energy"):
            record["ev_charger_car_energy"] = {
                cid: {**entry, "kwh": 0.0} for cid, entry in record["ev_charger_car_energy"].items()
            }
    return record


def _car_energy_entities(config: dict[str, Any]) -> list[str]:
    """Car-side entities to fetch with the slot history (ev-charging-losses D4)."""
    entities: list[str] = []
    for ev in _enabled_ev_chargers(config):
        sensor = str(ev.get("energy_added_sensor") or "").strip()
        soc = str(ev.get("soc_sensor") or "").strip()
        if sensor:
            entities.append(sensor)
        elif soc:
            entities.append(soc)
    return entities


def _enabled_ev_chargers(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw: Any = config.get("ev_chargers")
    if not isinstance(raw, list):
        return []
    return [
        cast("dict[str, Any]", ev)
        for ev in cast("list[Any]", raw)
        if isinstance(ev, dict) and cast("dict[str, Any]", ev).get("enabled", True)
    ]


def _ev_car_energy(
    config: dict[str, Any],
    ev_charger_energy: dict[str, float],
    history: dict[str, list[dict[str, Any]]],
    slot_start: datetime,
    slot_end: datetime,
) -> dict[str, dict[str, Any]]:
    """Per-charger car-side energy and its source (``sensor`` | ``soc``) for the slot."""
    result: dict[str, dict[str, Any]] = {}
    for ev in _enabled_ev_chargers(config):
        charger_id = str(ev.get("id") or "")
        if charger_id not in ev_charger_energy:
            continue
        sensor = str(ev.get("energy_added_sensor") or "").strip()
        soc = str(ev.get("soc_sensor") or "").strip()
        kwh: float | None = None
        source = "sensor" if sensor else "soc"
        if sensor:
            kwh = car_energy_from_added_sensor(
                history.get(sensor, []),
                float(
                    ev.get(
                        "energy_added_reset_threshold_kwh",
                        DEFAULT_ENERGY_ADDED_RESET_THRESHOLD_KWH,
                    )
                    or 0.0
                ),
            )
            if kwh is not None:
                kwh = cap_car_energy(kwh, float(ev_charger_energy.get(charger_id) or 0.0))
        elif soc:
            kwh = car_energy_from_soc(
                history.get(soc, []),
                float(ev.get("battery_capacity_kwh") or 0.0),
                slot_start,
                slot_end,
                float(ev.get("soc_stale_after_minutes", 15) or 15),
            )
        if kwh is not None:
            result[charger_id] = {"kwh": kwh, "source": source}
    return result


async def record_observation_from_current_state(
    config: dict[str, Any] | None = None,
    disaggregator: LoadDisaggregator | None = None,
):
    """Capture current system state and store as an observation."""
    if not config:
        config = _load_config()
    db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
    tz_name = config.get("timezone", "Europe/Stockholm")
    tz = pytz.timezone(tz_name)

    # Initialize store (in-place initialization is acceptable for the standalone script)
    store = LearningStore(db_path, tz)

    # Identify the just-finished 15-minute slot from the wall clock.
    now = datetime.now(tz)
    minute_block = (now.minute // 15) * 15
    slot_end = now.replace(minute=minute_block, second=0, microsecond=0)
    slot_start = slot_end - timedelta(minutes=15)

    # Gather Data
    input_sensors = config.get("input_sensors", {})

    # Helper to get sensor value and convert W to kW if needed.
    # Uses get_ha_sensor_kw_normalized which reads unit_of_measurement from HA
    # and only divides by 1000 when the sensor reports in Watts.
    # This correctly handles both W-reporting (most inverters) and
    # kW-reporting (Fronius SolarNet) sensors automatically.
    async def get_kw(key: str, default: float = 0.0) -> float:
        entity = input_sensors.get(key)
        if not entity:
            return default
        val = await get_ha_sensor_kw_normalized(str(entity))
        if val is None:
            return default
        return val

    # Power entities of this slot (disabled subsystems and unset sensors are skipped).
    sources = build_slot_sources(config)
    meter_type = sources.meter_type

    # Build batch of independent power sensor reads (Current Power State Snapshot).
    # The snapshot is the per-metric fallback when history integration gives no value.
    power_reads: list[tuple[str, Any]] = [
        (read_key, lambda k=read_key: get_kw(k))
        for read_key, entity in (
            ("pv_power", sources.pv),
            ("load_power", sources.load),
            ("battery_power", sources.battery),
            ("grid_power", sources.grid),
            ("grid_import_power", sources.grid_import),
            ("grid_export_power", sources.grid_export),
        )
        if entity
    ]
    for _, sensor in sources.water_heaters:
        power_reads.append((f"wh_{sensor}", lambda s=sensor: get_ha_sensor_kw_normalized(s)))
    for _, sensor in sources.ev_chargers:
        power_reads.append((f"ev_{sensor}", lambda s=sensor: get_ha_sensor_kw_normalized(s)))

    power_results = await gather_sensor_reads(power_reads, context="recorder_observation")

    pv_kw: float = power_results.get("pv_power") or 0.0
    total_load_kw: float = power_results.get("load_power") or 0.0
    battery_kw: float = power_results.get("battery_power") or 0.0

    # Disaggregate loads if disaggregator is provided (REV // ML2)
    controllable_kw = 0.0
    if disaggregator:
        controllable_kw = await disaggregator.update_current_power()
        load_kw = disaggregator.calculate_base_load(total_load_kw, controllable_kw)
        logger.info(
            f"Disaggregation: Total={total_load_kw:.3f}kW, Controllable={controllable_kw:.3f}kW -> Base={load_kw:.3f}kW"
        )
    else:
        load_kw = total_load_kw

    import_kw: float = 0.0
    export_kw: float = 0.0

    if meter_type == "dual":
        import_kw = power_results.get("grid_import_power") or 0.0
        export_kw = power_results.get("grid_export_power") or 0.0
    else:
        grid_net_kw: float = power_results.get("grid_power") or 0.0
        # Handle grid inversion for net meter type (REV F55)
        if sources.grid_inverted:
            grid_net_kw = -grid_net_kw
            logger.debug(f"Applied grid_power_inverted: net={grid_net_kw:.3f}kW")
        import_kw = max(0.0, grid_net_kw)
        export_kw = max(0.0, -grid_net_kw)

    # Apply battery inversion if configured (REV F55)
    if sources.battery_inverted:
        battery_kw = -battery_kw
        logger.debug(f"Applied battery_power_inverted: {battery_kw:.3f}kW")

    # Standard inverter convention: positive = discharge, negative = charge
    discharge_power_kw = max(0.0, battery_kw)
    charge_power_kw = max(0.0, -battery_kw)

    # One history request for every power entity of the slot, integrated over exactly
    # [slot_start, slot_end]. A failed request leaves every metric on its snapshot.
    car_entities = _car_energy_entities(config)
    history = await get_power_history_batch(
        sources.entity_ids() + car_entities, slot_start, slot_end
    )
    series = {entity: parse_power_states(states) for entity, states in (history or {}).items()}
    energy = compute_slot_energy(sources, series, slot_start, slot_end)

    def or_snapshot(integrated: float | None, snapshot_kw: float) -> float:
        """History energy, or the power snapshot x 0.25 h when integration gave no value."""
        return integrated if integrated is not None else snapshot_kw * 0.25

    pv_kwh = or_snapshot(energy.pv, max(0.0, pv_kw))
    import_kwh = or_snapshot(energy.import_kwh, import_kw)
    export_kwh = or_snapshot(energy.export_kwh, export_kw)
    batt_charge_kwh = or_snapshot(energy.batt_charge, charge_power_kw)
    batt_discharge_kwh = or_snapshot(energy.batt_discharge, discharge_power_kw)

    # EV charging energy (per charger and aggregate)
    ev_charging_kwh = 0.0
    ev_charger_energy: dict[str, float] = {}  # Task 8.1: per-device recording
    for charger_id, sensor in sources.ev_chargers:
        integrated = energy.ev.get(sensor)
        device_kwh = or_snapshot(integrated, max(0.0, power_results.get(f"ev_{sensor}") or 0.0))
        ev_charging_kwh += device_kwh
        if charger_id:
            ev_charger_energy[charger_id] = device_kwh
        source = "history energy" if integrated is not None else "snapshot fallback"
        logger.debug(f"EV {charger_id}: {source}={device_kwh:.3f} kWh")

    ev_charger_car_energy = _ev_car_energy(
        config, ev_charger_energy, history or {}, slot_start, slot_end
    )

    # Water heater energy (per heater and aggregate)
    water_kwh = 0.0
    water_heater_energy: dict[str, float] = {}  # Task 8.1: per-device recording
    water_heater_devices: dict[str, dict[str, Any]] = {}
    water_methods: list[str] = []
    for heater_id, sensor in sources.water_heaters:
        integrated = energy.water.get(sensor)
        cutoff = sources.water_idle_power_thresholds_kw.get(sensor, DEFAULT_IDLE_POWER_THRESHOLD_KW)
        snapshot = power_results.get(f"wh_{sensor}")
        active_snapshot = (
            max(0.0, normalize_active_power_kw(snapshot, "kW", cutoff) or 0.0)
            if snapshot is not None
            else None
        )
        source = (
            "power_history"
            if integrated is not None
            else "snapshot"
            if active_snapshot is not None
            else "unavailable"
        )
        device_kwh = (
            integrated
            if integrated is not None
            else active_snapshot * 0.25
            if active_snapshot is not None
            else 0.0
        )
        water_methods.append(source)
        water_kwh += device_kwh
        if heater_id and source != "unavailable":
            water_heater_energy[heater_id] = device_kwh
        if heater_id:
            water_heater_devices[heater_id] = {
                "energy_kwh": device_kwh if source != "unavailable" else None,
                "source": source,
                "idle_power_threshold_kw": cutoff,
                "coverage": "complete" if source != "unavailable" else "unavailable",
            }
        logger.debug("Water %s: %s=%.3f kWh", heater_id, source, device_kwh)

    def method_for(integrated: float | None, configured: bool, enabled: bool = True) -> str:
        if not enabled:
            return "disabled_zero"
        if not configured:
            return "unconfigured_zero"
        return "power_history" if integrated is not None else "snapshot"

    system_value = config.get("system")
    system_config = cast("dict[str, Any]", system_value) if isinstance(system_value, dict) else {}
    ev_config_value = config.get("ev_chargers")
    ev_config = (
        cast("list[dict[str, Any]]", ev_config_value) if isinstance(ev_config_value, list) else []
    )
    water_config_value = config.get("water_heaters")
    water_configured_any = isinstance(water_config_value, list) and bool(
        cast("list[Any]", water_config_value)
    )
    # The flag wins: with has_water_heater false this is empty even with stale entries.
    water_config = active_water_heaters(config)
    ev_methods = [method_for(energy.ev.get(sensor), True) for _, sensor in sources.ev_chargers]

    def aggregate_method(methods: list[str], enabled: bool, configured: bool) -> str:
        if not enabled:
            return "disabled_zero"
        if not methods:
            return "unconfigured_zero"
        if not configured:
            return "mixed"
        if "unavailable" in methods:
            return "unknown"
        if "snapshot" in methods:
            return "mixed" if "power_history" in methods else "snapshot"
        return "power_history"

    ev_method = aggregate_method(
        ev_methods,
        bool(system_config.get("has_ev_charger", False))
        and (not ev_config or any(item.get("enabled", True) for item in ev_config)),
        bool(sources.ev_chargers)
        and all(item.get("sensor") for item in ev_config if item.get("enabled", True)),
    )
    water_method = aggregate_method(
        water_methods,
        bool(system_config.get("has_water_heater", True))
        and (not water_configured_any or bool(water_config)),
        bool(sources.water_heaters) and all(item.get("sensor") for item in water_config),
    )
    if any(not item.get("sensor") for item in water_config):
        water_method = "unknown"
    if not water_methods and water_method == "unconfigured_zero":
        water_heater_devices = {}

    # Isolate base load: subtract known deferrable loads from total load.
    # Applies when load is the integrated total, or a power snapshot without disaggregator.
    # Skipped when the disaggregator already provided a base-load-only snapshot.
    if energy.load is not None:
        load_kwh = isolate_base_load(energy.load, ev_charging_kwh, water_kwh)
        load_method = (
            "unconfigured_zero"
            if not sources.load
            else "mixed"
            if any(
                method in {"snapshot", "mixed", "unconfigured_zero"}
                for method in (ev_method, water_method)
            )
            else "derived_history"
        )
    elif disaggregator:
        load_kwh = max(0.0, load_kw) * 0.25
        load_method = method_for(None, bool(sources.load))
    else:
        load_kwh = isolate_base_load(max(0.0, load_kw) * 0.25, ev_charging_kwh, water_kwh)
        load_method = (
            "mixed"
            if any(
                method in {"snapshot", "mixed", "unconfigured_zero"}
                for method in (ev_method, water_method)
            )
            else method_for(None, bool(sources.load))
        )

    # Battery
    soc_entity = input_sensors.get("battery_soc")
    soc_percent = None
    soc_source = "unavailable"
    if soc_entity:
        soc_percent = await get_ha_sensor_float(soc_entity)

    if soc_percent is None:
        # Fallback: Try to get last known SoC from DB
        cached_soc = await store.get_system_state("last_known_soc")
        if cached_soc and soc_entity:
            try:
                soc_percent = float(cached_soc)
                soc_source = "cached"
                logger.warning(
                    f"Battery SoC sensor ({soc_entity}) unavailable. "
                    f"Using last known value: {soc_percent:.1f}%"
                )
            except ValueError:
                logger.error(
                    f"Cached SoC value is corrupted: '{cached_soc}'. "
                    "Cannot use fallback. Skipping observation."
                )
                soc_percent = None

        if soc_percent is None and soc_entity:
            logger.warning(
                f"Battery SoC sensor ({soc_entity}) unavailable and no valid cached value. "
                "Skipping observation record."
            )
            await store.close()
            return
    else:
        soc_source = "live"
        # Valid SoC obtained - update cache
        await store.set_system_state("last_known_soc", str(soc_percent))

    # Fetch Price Data (REV // Complete Cost Reality Fix)
    prices = await get_current_slot_prices(config)
    import_price = prices.get("import_price_sek_kwh") if prices else None
    export_price = prices.get("export_price_sek_kwh") if prices else None

    if prices:
        logger.info(f"Price data fetched: Import={import_price:.4f}, Export={export_price:.4f}")
    else:
        logger.warning("Failed to fetch price data for current observation")

    # Capture actual component paths after all fallback and derived-load choices.
    recording = recording_metadata(
        config,
        {
            "pv": {
                "method": method_for(
                    energy.pv, bool(sources.pv), bool(system_config.get("has_solar", True))
                ),
                "owner": "recorder",
            },
            "import": {
                "method": method_for(
                    energy.import_kwh,
                    bool(sources.grid_import if meter_type == "dual" else sources.grid),
                    True,
                ),
                "owner": "recorder",
            },
            "export": {
                "method": method_for(
                    energy.export_kwh,
                    bool(sources.grid_export if meter_type == "dual" else sources.grid),
                    True,
                ),
                "owner": "recorder",
            },
            "load": {"method": load_method, "owner": "recorder"},
            "water": {"method": water_method, "owner": "recorder"},
            "ev": {"method": ev_method, "owner": "recorder"},
            "battery_charge": {
                "method": method_for(
                    energy.batt_charge,
                    bool(sources.battery),
                    bool(system_config.get("has_battery", True)),
                ),
                "owner": "recorder",
            },
            "battery_discharge": {
                "method": method_for(
                    energy.batt_discharge,
                    bool(sources.battery),
                    bool(system_config.get("has_battery", True)),
                ),
                "owner": "recorder",
            },
        },
        soc_source,
    )

    # Construct Record
    record = {
        "slot_start": slot_start,
        "slot_end": slot_end,
        "pv_kwh": pv_kwh,
        "load_kwh": load_kwh,
        "import_kwh": import_kwh,
        "export_kwh": export_kwh,
        "water_kwh": (
            None
            if water_methods and all(method == "unavailable" for method in water_methods)
            else water_kwh
        ),
        "water_heater_energy": water_heater_energy if water_heater_energy else None,  # Task 8.2
        "ev_charging_kwh": ev_charging_kwh,
        "ev_charger_energy": ev_charger_energy if ev_charger_energy else None,
        "ev_charger_car_energy": ev_charger_car_energy or None,
        "batt_charge_kwh": batt_charge_kwh,
        "batt_discharge_kwh": batt_discharge_kwh,
        "soc_end_percent": soc_percent,
        "import_price_sek_kwh": import_price,
        "export_price_sek_kwh": export_price,
        "created_at": datetime.now(UTC).isoformat(),
        "quality_flags": {
            "source": "recorder",
            "recording": recording,
            "water_heater_energy": {
                "schema_version": WATER_HEATER_ENERGY_SCHEMA_VERSION,
                "semantics": WATER_HEATER_ENERGY_SEMANTICS,
                "devices": water_heater_devices,
            },
        },
    }

    logger.info(
        f"Recording observation for {slot_start}: SOC={soc_percent}% "
        f"PV={pv_kwh:.3f}kWh Load={load_kwh:.3f}kWh Water={water_kwh:.3f}kWh "
        f"EV={ev_charging_kwh:.3f}kWh Bat={battery_kw:.3f}kW"
    )

    # Validate energy values before storage
    try:
        max_kwh = get_max_energy_per_slot(config)
        original_record = record
        record = validate_energy_values(record, max_kwh)
        sanitized_components = {
            "pv_kwh": "pv",
            "load_kwh": "load",
            "import_kwh": "import",
            "export_kwh": "export",
            "water_kwh": "water",
            "ev_charging_kwh": "ev",
            "batt_charge_kwh": "battery_charge",
            "batt_discharge_kwh": "battery_discharge",
        }
        for field, component in sanitized_components.items():
            if record.get(field) != original_record.get(field):
                recording["components"][component]["method"] = "unknown"
        # Keep per-charger energy consistent with a rejected (zeroed) aggregate.
        record = zero_rejected_ev_energy(record)
    except ValueError as e:
        logger.warning(f"Could not validate energy values: {e}. Proceeding with raw values.")

    # Store
    df = pd.DataFrame([record])
    await store.store_slot_observations(df)
    await store.close()  # Clean up async engine connections


async def _sleep_until_next_quarter() -> None:
    """Sleep until the next 15-minute boundary (UTC-based)."""
    now = datetime.now(UTC)
    minute_block = (now.minute // 15) * 15
    current_slot = now.replace(minute=minute_block, second=0, microsecond=0)
    next_slot = current_slot + timedelta(minutes=15)
    sleep_seconds = max(5.0, (next_slot - now).total_seconds())
    await asyncio.sleep(sleep_seconds)


async def backfill_missing_prices():
    """Backfill missing price data for historical observations."""
    try:
        from backend.core.prices import get_nordpool_data

        config = _load_config()
        db_path = config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
        tz_name = config.get("timezone", "Europe/Stockholm")
        tz = pytz.timezone(tz_name)

        store = LearningStore(db_path, tz)
        observations = await store.get_history_range(
            datetime.now(tz) - timedelta(days=30), datetime.now(tz)
        )

        missing_any = any(obs.get("import_price_sek_kwh") is None for obs in observations)
        if not missing_any:
            logger.info("[recorder] No missing prices to backfill.")
            await store.close()
            return

        logger.info("[recorder] Backfilling missing prices...")
        price_data = await get_nordpool_data()
        if not price_data:
            logger.error("[recorder] Failed to fetch price data for backfill.")
            await store.close()
            return

        indexed_prices = {p["start_time"]: p for p in price_data}
        rows_to_update: list[dict[str, Any]] = []

        for obs in observations:
            if obs.get("import_price_sek_kwh") is None:
                slot_start_raw = obs["slot_start"]
                if isinstance(slot_start_raw, str):
                    slot_start = datetime.fromisoformat(slot_start_raw)
                else:
                    slot_start = slot_start_raw

                if slot_start.tzinfo is None:
                    slot_start = tz.localize(slot_start)
                else:
                    slot_start = slot_start.astimezone(tz)

                # Round to nearest 15/60 min boundary if needed, but get_nordpool_data handles it
                # We need exact match or closest previous
                price_slot = indexed_prices.get(slot_start)
                if price_slot:
                    # Never overwrite an export price the slot already has
                    # (store_slot_prices lets non-null new values win).
                    export_price = (
                        None
                        if obs.get("export_price_sek_kwh") is not None
                        else price_slot["export_price_sek_kwh"]
                    )
                    rows_to_update.append(
                        {
                            "slot_start": obs["slot_start"],
                            # slot_end is NOT NULL: SQLite checks it on the insert
                            # half of the upsert even when the row already exists.
                            "slot_end": obs.get("slot_end"),
                            "import_price_sek_kwh": price_slot["import_price_sek_kwh"],
                            "export_price_sek_kwh": export_price,
                        }
                    )

        if rows_to_update:
            updated_count = len(rows_to_update)
            await store.store_slot_prices(rows_to_update)
            logger.info(f"[recorder] Backfilled {updated_count} observation prices.")

        await store.close()
    except Exception as e:
        logger.error(f"[recorder] Price backfill failed: {e}")
        import traceback

        traceback.print_exc()


async def main() -> int:
    """Background recorder loop: capture observations every 15 minutes."""
    logger.info("[recorder] Starting live observation recorder (15m cadence)")

    config = _load_config()

    # Run backfill on startup
    try:
        # BackfillEngine.run is now async.
        backfill = BackfillEngine()
        await backfill.run()
    except Exception as e:
        logger.warning("[recorder] Backfill failed: %s", e)

    # Run Price Backfill on startup
    await backfill_missing_prices()

    # Initialize disaggregator (REV // ML2)
    disaggregator = LoadDisaggregator(config)

    while True:
        try:
            await record_observation_from_current_state(config, disaggregator)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("[recorder] Error while recording observation: %s", exc)

        await _sleep_until_next_quarter()


if __name__ == "__main__":
    import contextlib

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
