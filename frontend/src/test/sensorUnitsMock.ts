/** Entity whose fake Home Assistant state has no unit. */
export const UNITLESS_ENTITY = 'sensor.unitless'

/**
 * Stand-in for POST /api/setup/sensor-units: the unitless entity is listed while it appears
 * anywhere in the draft config, with its override (or null), like the real backend decides.
 */
export function fakeSensorUnits(config: Record<string, unknown>) {
    const { sensor_unit_overrides: overrides, ...rest } = config as {
        sensor_unit_overrides?: Record<string, string>
    }
    const referenced = JSON.stringify(rest).includes(`"${UNITLESS_ENTITY}"`)
    const override =
        overrides?.[UNITLESS_ENTITY] === 'W' || overrides?.[UNITLESS_ENTITY] === 'kW'
            ? overrides[UNITLESS_ENTITY]
            : null
    return {
        unit_needed: referenced
            ? [{ entity_id: UNITLESS_ENTITY, settings_path: 'x.y', live_value: 1200, override }]
            : [],
    }
}
