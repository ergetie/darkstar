/** Mirrors the backend default in planner/battery_limits.py resolve_battery_power_limits (48 V when unset). */
export const DEFAULT_BATTERY_VOLTAGE_V = 48

/**
 * Effective battery power for an Amp limit (amps x nominal voltage), formatted for
 * the settings hint, e.g. "~4.80 kW at 48 V". Returns null when amps is not a positive number.
 */
export function effectiveBatteryKw(amps: unknown, voltage: unknown): string | null {
    const a = typeof amps === 'string' && amps.trim() === '' ? NaN : Number(amps)
    if (!(a > 0)) return null
    const v = typeof voltage === 'string' && voltage.trim() === '' ? NaN : Number(voltage)
    const volts = v > 0 ? v : DEFAULT_BATTERY_VOLTAGE_V
    return `~${((a * volts) / 1000).toFixed(2)} kW at ${volts} V`
}
