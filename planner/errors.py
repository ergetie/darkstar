from __future__ import annotations

from enum import StrEnum
from typing import Any


class PlannerErrorCode(StrEnum):
    CONFIG_INVALID = "CONFIG_INVALID"
    INITIAL_SOC_OUT_OF_RANGE = "INITIAL_SOC_OUT_OF_RANGE"
    DATA_STALE = "DATA_STALE"
    EV_MISSING_POWER = "EV_MISSING_POWER"
    EV_INVALID_CAPACITY = "EV_INVALID_CAPACITY"
    EV_DEADLINE_PAST = "EV_DEADLINE_PAST"
    PRICES_UNAVAILABLE = "PRICES_UNAVAILABLE"
    FORECAST_UNAVAILABLE = "FORECAST_UNAVAILABLE"
    NUMERIC_INVALID = "NUMERIC_INVALID"
    SOLVER_INFEASIBLE = "SOLVER_INFEASIBLE"
    SOLVER_TIMEOUT = "SOLVER_TIMEOUT"
    SOLVER_UNDEFINED = "SOLVER_UNDEFINED"
    INVALID_SCHEDULE = "INVALID_SCHEDULE"
    HA_UNAVAILABLE = "HA_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


_USER_MESSAGES: dict[PlannerErrorCode, str] = {
    PlannerErrorCode.CONFIG_INVALID: "Battery configuration is invalid",
    PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE: "Battery state of charge reading is out of range",
    PlannerErrorCode.DATA_STALE: "Battery state of charge reading is stale",
    PlannerErrorCode.EV_MISSING_POWER: "EV charger is missing required power configuration",
    PlannerErrorCode.EV_INVALID_CAPACITY: "EV charger has invalid battery capacity",
    PlannerErrorCode.EV_DEADLINE_PAST: "EV charging deadline has already passed",
    PlannerErrorCode.PRICES_UNAVAILABLE: "Price data is unavailable or insufficient",
    PlannerErrorCode.FORECAST_UNAVAILABLE: "Forecast data is unavailable or insufficient",
    PlannerErrorCode.NUMERIC_INVALID: "Price or forecast data contains invalid values",
    PlannerErrorCode.SOLVER_INFEASIBLE: "Planner found no feasible schedule",
    PlannerErrorCode.SOLVER_TIMEOUT: "Planner solver timed out",
    PlannerErrorCode.SOLVER_UNDEFINED: "Planner solver returned an undefined result",
    PlannerErrorCode.INVALID_SCHEDULE: "Planner produced an invalid schedule",
    PlannerErrorCode.HA_UNAVAILABLE: "Home Assistant is unreachable",
    PlannerErrorCode.UNKNOWN: "An unexpected planner error occurred",
}

_FIX_HINTS: dict[PlannerErrorCode, list[str]] = {
    PlannerErrorCode.CONFIG_INVALID: [
        "Check battery settings: ensure min_soc_percent < max_soc_percent, capacity_kwh > 0, and charge/discharge power > 0.",
    ],
    PlannerErrorCode.INITIAL_SOC_OUT_OF_RANGE: [
        "Verify the battery SoC sensor is reporting a value between 0 and capacity. Check sensor wiring or recalibrate.",
    ],
    PlannerErrorCode.DATA_STALE: [
        "The battery SoC sensor has not updated in over 30 minutes. Check the sensor connection in Home Assistant.",
    ],
    PlannerErrorCode.EV_MISSING_POWER: [
        "Open Settings and set the EV charger's power: max_current_a and phases for a current-controlled charger, or rated_power_kw for a binary (on/off) charger. The charger is excluded from planning until this is fixed.",
    ],
    PlannerErrorCode.EV_INVALID_CAPACITY: [
        "Open Settings and set battery_capacity_kwh for the EV charger to a positive value matching the vehicle's battery size.",
    ],
    PlannerErrorCode.EV_DEADLINE_PAST: [
        "The EV charging deadline is in the past. Update the departure time in Settings.",
    ],
    PlannerErrorCode.PRICES_UNAVAILABLE: [
        "Price data is missing or covers less than 4 hours ahead. Check the price feed integration and ensure it is connected and up to date.",
    ],
    PlannerErrorCode.FORECAST_UNAVAILABLE: [
        "Forecast data is empty or does not cover the planning horizon. Check the forecast integration.",
    ],
    PlannerErrorCode.NUMERIC_INVALID: [
        "Price or forecast data contains NaN or Inf values. This may indicate a problem with the data source integration.",
    ],
    PlannerErrorCode.SOLVER_INFEASIBLE: [
        "The planner could not find a feasible schedule. Check for conflicting constraints in the configuration.",
    ],
    PlannerErrorCode.SOLVER_TIMEOUT: [
        "The solver took too long. This may be transient — the planner will retry automatically.",
    ],
    PlannerErrorCode.SOLVER_UNDEFINED: [
        "The solver returned an undefined result. The planner will retry automatically.",
    ],
    PlannerErrorCode.INVALID_SCHEDULE: [
        "The planner produced an empty or malformed schedule. Check the logs for details and retry.",
    ],
    PlannerErrorCode.HA_UNAVAILABLE: [
        "Home Assistant did not respond. Planning is paused until it returns and will resume automatically — no action needed unless the outage persists.",
    ],
    PlannerErrorCode.UNKNOWN: [
        "An unexpected error occurred. Check the backend logs for the full traceback.",
    ],
}


def user_message(code: PlannerErrorCode) -> str:
    return _USER_MESSAGES[code]


def fix_hints(code: PlannerErrorCode) -> list[str]:
    return _FIX_HINTS[code]


def is_config_blocking(code: PlannerErrorCode) -> bool:
    return code in {
        PlannerErrorCode.CONFIG_INVALID,
        PlannerErrorCode.EV_MISSING_POWER,
        PlannerErrorCode.EV_INVALID_CAPACITY,
    }


def is_transient(code: PlannerErrorCode) -> bool:
    return code in {
        PlannerErrorCode.PRICES_UNAVAILABLE,
        PlannerErrorCode.FORECAST_UNAVAILABLE,
        PlannerErrorCode.SOLVER_TIMEOUT,
        PlannerErrorCode.HA_UNAVAILABLE,
    }


def is_warning_only(code: PlannerErrorCode) -> bool:
    return code in {
        PlannerErrorCode.DATA_STALE,
        PlannerErrorCode.EV_DEADLINE_PAST,
    }


class PlannerError(Exception):
    def __init__(
        self,
        code: PlannerErrorCode,
        message: str = "",
        fix_hint: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or user_message(code)
        self.fix_hint = fix_hint or (fix_hints(code)[0] if fix_hints(code) else "")
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "fix_hint": self.fix_hint,
            "details": self.details,
        }
