import { describe, expect, it } from 'vitest'
import { isPowerModeEntity } from './logic'
import type { HaEntity } from './types'

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
