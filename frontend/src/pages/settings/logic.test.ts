import { describe, expect, it } from 'vitest'
import { isPowerModeEntity, shouldRenderField } from './logic'
import type { BaseField, HaEntity } from './types'

const entities: HaEntity[] = [
    { entity_id: 'sensor.grid_l1_current', friendly_name: 'L1 current', domain: 'sensor', unit_of_measurement: 'A' },
    { entity_id: 'sensor.grid_l1_power', friendly_name: 'L1 power', domain: 'sensor', unit_of_measurement: 'W' },
    { entity_id: 'sensor.grid_l1_kw', friendly_name: 'L1 power kW', domain: 'sensor', unit_of_measurement: 'kW' },
    {
        entity_id: 'sensor.grid_l1_no_unit',
        friendly_name: 'L1 no unit',
        domain: 'sensor',
        device_class: 'power',
    },
]

describe('isPowerModeEntity', () => {
    it('returns false for a current sensor', () => {
        expect(isPowerModeEntity('sensor.grid_l1_current', entities)).toBe(false)
    })

    it('returns true for a watt sensor', () => {
        expect(isPowerModeEntity('sensor.grid_l1_power', entities)).toBe(true)
    })

    it('returns true for a kilowatt sensor', () => {
        expect(isPowerModeEntity('sensor.grid_l1_kw', entities)).toBe(true)
    })

    it('falls back to device_class when unit is missing', () => {
        expect(isPowerModeEntity('sensor.grid_l1_no_unit', entities)).toBe(true)
    })

    it('returns false when no entity is selected', () => {
        expect(isPowerModeEntity(undefined, entities)).toBe(false)
    })

    it('returns false when the entity is unknown', () => {
        expect(isPowerModeEntity('sensor.does_not_exist', entities)).toBe(false)
    })
})

function conditionalField(
    configKey: string,
    value?: string | boolean | number | (string | boolean | number)[],
): BaseField {
    return {
        key: configKey,
        label: configKey,
        path: configKey.split('.'),
        type: 'text',
        showIf: { configKey, value },
    }
}

describe('shouldRenderField', () => {
    it('uses current system form values before saved config and falls back when absent', () => {
        const profileField = conditionalField('system.inverter_profile', 'generic')
        const savedConfig = { system: { inverter_profile: 'deye' } }

        expect(shouldRenderField(profileField, { 'system.inverter_profile': 'generic' }, savedConfig)).toBe(true)
        expect(shouldRenderField(profileField, { 'system.inverter_profile': 'solis' }, savedConfig)).toBe(false)
        expect(shouldRenderField(profileField, {}, { system: { inverter_profile: 'generic' } })).toBe(true)
    })

    it('compares booleans explicitly, including boolean arrays', () => {
        const solarField = conditionalField('system.has_solar', true)
        const trueArrayField = conditionalField('system.has_solar', [true])

        expect(shouldRenderField(solarField, { 'system.has_solar': false }, { system: { has_solar: true } })).toBe(
            false,
        )
        expect(shouldRenderField(solarField, {}, { system: { has_solar: true } })).toBe(true)
        expect(shouldRenderField(conditionalField('system.has_solar', false), {}, {})).toBe(false)
        expect(shouldRenderField(trueArrayField, { 'system.has_solar': true }, { system: { has_solar: false } })).toBe(
            true,
        )
        expect(shouldRenderField(trueArrayField, { 'system.has_solar': false }, { system: { has_solar: true } })).toBe(
            false,
        )
    })

    it('matches string arrays against current form values and saved config', () => {
        const field = conditionalField('system.inverter_profile', ['generic', 'deye'])

        expect(
            shouldRenderField(
                field,
                { 'system.inverter_profile': 'generic' },
                { system: { inverter_profile: 'solis' } },
            ),
        ).toBe(true)
        expect(
            shouldRenderField(field, { 'system.inverter_profile': 'solis' }, { system: { inverter_profile: 'deye' } }),
        ).toBe(false)
        expect(shouldRenderField(field, {}, { system: { inverter_profile: 'deye' } })).toBe(true)
    })
})
