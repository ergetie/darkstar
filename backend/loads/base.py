from enum import Enum


class LoadType(Enum):
    BINARY = "binary"  # On/Off (e.g. some water heaters)
    FIXED = "fixed"  # Alias for binary/static loads
    VARIABLE = "variable"  # Variable power (e.g. smart EV chargers)
    CURRENT = "current"  # Variable ampere setpoint (e.g. current-controlled EV chargers)
    MODULATING = "modulating"  # Modulating power output (e.g. some water heaters)


# Accepted `type` values per device kind, derived from LoadType so config
# validation (backend/api/routers/config.py) and the load-disaggregation
# runtime (backend/loads/service.py) can't silently drift apart.
EV_CHARGER_LOAD_TYPES = {LoadType.BINARY.value, LoadType.CURRENT.value}
WATER_HEATER_LOAD_TYPES = {LoadType.BINARY.value, LoadType.MODULATING.value}


class DeferrableLoad:
    """Base class for loads that can be deferred or controlled."""

    def __init__(
        self,
        load_id: str,
        name: str,
        sensor_key: str,
        load_type: LoadType = LoadType.VARIABLE,
        nominal_power_kw: float = 0.0,
        disabled_reason: str | None = None,
    ):
        self.id = load_id
        self.name = name
        self.sensor_key = sensor_key
        self.type = load_type
        self.nominal_power_kw = nominal_power_kw
        self.current_power_kw = 0.0
        self.is_healthy = True
        self.disabled_reason = disabled_reason

    def __repr__(self) -> str:
        disabled = f" DISABLED({self.disabled_reason})" if self.disabled_reason else ""
        return f"<DeferrableLoad id={self.id} type={self.type.value} power={self.current_power_kw}kW{disabled}>"
