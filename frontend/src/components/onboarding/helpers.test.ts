import { describe, expect, it } from 'vitest'
import type { InverterProfile } from '../../pages/settings/types'
import { applicableSteps, steps } from './steps'
import { configDiff, hasFiniteNumber, prefillHighConfidence, setPath, settingLabel, type WizardConfig } from './helpers'

const profile: InverterProfile = {
    name: 'test-profile',
    description: 'Test inverter',
    supported_brands: [],
    version: '1',
    schema_version: 2,
    entities: {},
    modes: {},
    behavior: { control_unit: 'W' },
}

const config = (overrides: Record<string, unknown> = {}) =>
    ({
        system: {
            has_solar: false,
            has_battery: false,
            has_water_heater: false,
            has_ev_charger: false,
            grid_meter_type: 'net',
            grid: { max_power_kw: 5 },
            ...((overrides.system as Record<string, unknown> | undefined) ?? {}),
        },
        battery: {},
        input_sensors: {},
        ...overrides,
    }) as WizardConfig

describe('onboarding step rules', () => {
    it('only includes hardware steps selected in the system definition', () => {
        const baseline = applicableSteps(config()).map((step) => step.id)
        const withFeatures = applicableSteps(
            config({
                system: { has_solar: true, has_battery: true, has_water_heater: true, has_ev_charger: true },
            }),
        ).map((step) => step.id)

        expect(baseline).not.toContain('solar')
        expect(baseline).not.toContain('battery')
        expect(baseline).not.toContain('water')
        expect(baseline).not.toContain('ev')
        expect(withFeatures).toEqual(expect.arrayContaining(['solar', 'battery', 'water', 'ev']))
    })

    it('requires charge and discharge power before completing battery setup', () => {
        const batteryStep = steps.find((step) => step.id === 'battery')!
        const values = config({
            system: { has_battery: true, inverter_profile: profile.name },
            battery: { capacity_kwh: 8, min_soc_percent: 10, max_soc_percent: 90 },
        })

        expect(batteryStep.isComplete(values, [profile])).toBe(false)
        const complete = setPath(setPath(values, 'battery.max_charge_w', 4000), 'battery.max_discharge_w', 4000)
        expect(batteryStep.isComplete(complete, [profile])).toBe(true)
    })

    it('accepts a zero minimum state of charge but blocks missing and out-of-range values', () => {
        const batteryStep = steps.find((step) => step.id === 'battery')!
        const values = config({
            system: { has_battery: true, inverter_profile: profile.name },
            battery: {
                capacity_kwh: 8,
                min_soc_percent: 0,
                max_soc_percent: 90,
                max_charge_w: 4000,
                max_discharge_w: 4000,
            },
        })

        expect(batteryStep.isComplete(values, [profile])).toBe(true)
        expect(batteryStep.isComplete(setPath(values, 'battery.min_soc_percent', ''), [profile])).toBe(false)
        expect(batteryStep.isComplete(setPath(values, 'battery.min_soc_percent', 101), [profile])).toBe(false)
    })

    it('preserves every configured water heater and EV entry when building their save patches', () => {
        const waterHeaters = [
            { id: 'main', name: 'Main tank', power_kw: 3, advanced_limit_c: 70 },
            { id: 'annex', name: 'Annex tank', power_kw: 2, advanced_limit_c: 65 },
        ]
        const evChargers = [
            { id: 'garage', name: 'Garage charger', type: 'current', phases: [1, 2, 3], advanced_control: 'eco' },
            { id: 'driveway', name: 'Driveway charger', type: 'binary', rated_power_kw: 7.2 },
        ]
        const current = config({ water_heaters: waterHeaters, ev_chargers: evChargers })

        expect(steps.find((step) => step.id === 'water')!.buildPatch(current)).toEqual({ water_heaters: waterHeaters })
        expect(steps.find((step) => step.id === 'ev')!.buildPatch(current)).toEqual({ ev_chargers: evChargers })
    })

    it('treats zero coordinates as present and rejects empty coordinates', () => {
        const pricing = steps.find((step) => step.id === 'pricing')!
        const values = config({
            system: { location: { latitude: 0, longitude: 0 } },
            nordpool: { price_area: 'SE3', currency: 'SEK' },
            timezone: 'Europe/Stockholm',
        })

        expect(pricing.isComplete(values, [])).toBe(true)
        expect(pricing.isComplete(setPath(values, 'system.location.latitude', ''), [])).toBe(false)
        expect(hasFiniteNumber(0)).toBe(true)
        expect(hasFiniteNumber('')).toBe(false)
    })

    it('includes removed configuration paths in the review diff with friendly labels', () => {
        const changes = configDiff(
            { water_heaters: [{ name: 'Main tank', power_kw: 3 }], input_sensors: { load_power: 'sensor.old' } },
            { water_heaters: [{ name: 'Main tank' }], input_sensors: { load_power: 'sensor.new' } },
        )

        expect(changes).toContainEqual({ path: 'water_heaters.0.power_kw', before: 3, after: undefined })
        expect(changes).toContainEqual({
            path: 'input_sensors.load_power',
            before: 'sensor.old',
            after: 'sensor.new',
        })
        expect(settingLabel('water_heaters.0.power_kw')).toBe('Water heater 1 · Rated power')
        expect(settingLabel('input_sensors.load_power')).toBe('House load power sensor')
    })

    it('prefills only high-confidence values into empty fields and preserves configured values', () => {
        const initial = config({ input_sensors: { load_power: 'sensor.existing' } })
        const result = prefillHighConfidence(
            initial,
            {
                input_sensors: {
                    load_power: 'sensor.overwrite',
                    grid_power: 'sensor.grid',
                    battery_soc: 'sensor.soc',
                },
            },
            {
                'input_sensors.load_power': [{ confidence: 'high' }],
                'input_sensors.grid_power': [{ confidence: 'medium' }],
                'input_sensors.battery_soc': [{ confidence: 'high' }],
            },
        )

        const sensors = result.input_sensors as Record<string, unknown>
        expect(sensors.load_power).toBe('sensor.existing')
        expect(sensors.grid_power).toBeUndefined()
        expect(sensors.battery_soc).toBe('sensor.soc')
    })
})
