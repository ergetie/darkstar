/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest'

/**
 * The backend alone decides which config paths are power sensors. These sources must stay
 * generic: any config path naming a power sensor here would be a second, drifting list.
 */
const FORBIDDEN = [
    'ev_chargers',
    'water_heaters',
    'load_balancing',
    'input_sensors',
    'power_sensor',
    'phase_sensor',
    'pv_power',
    'load_power',
    'grid_power',
    'grid_import_power',
    'grid_export_power',
    'battery_power',
    'excess_pv',
    'give_way',
]

const SOURCES = import.meta.glob<string>(
    ['./sensorUnits.ts', './useUnitNeeded.ts', '../components/SensorUnitSelect.tsx', '../components/EntitySelect.tsx'],
    { query: '?raw', import: 'default', eager: true },
)

function forbiddenPaths(source: string): string[] {
    return FORBIDDEN.filter((needle) => source.includes(needle))
}

describe('power sensor field list guard', () => {
    it('checks all four guarded sources', () => {
        expect(Object.keys(SOURCES)).toHaveLength(4)
    })

    it.each(Object.entries(SOURCES))('%s names no power-sensor config path', (_file, source) => {
        expect(forbiddenPaths(source)).toEqual([])
    })

    it('detects a hardcoded power-sensor path', () => {
        expect(forbiddenPaths("const paths = ['ev_chargers.0.power_sensor', 'input_sensors.pv_power']")).toEqual([
            'ev_chargers',
            'input_sensors',
            'power_sensor',
            'pv_power',
        ])
    })
})
