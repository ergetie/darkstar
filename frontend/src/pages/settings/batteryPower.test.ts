import { describe, expect, it } from 'vitest'
import { DEFAULT_BATTERY_VOLTAGE_V, effectiveBatteryKw } from './batteryPower'

describe('effectiveBatteryKw', () => {
    it('formats amps x voltage as kW', () => {
        expect(effectiveBatteryKw('100', '48')).toBe('~4.80 kW at 48 V')
        expect(effectiveBatteryKw(185, 51.2)).toBe('~9.47 kW at 51.2 V')
    })

    it('returns null for empty, zero, negative or non-numeric amps', () => {
        expect(effectiveBatteryKw('', '48')).toBeNull()
        expect(effectiveBatteryKw(undefined, '48')).toBeNull()
        expect(effectiveBatteryKw('0', '48')).toBeNull()
        expect(effectiveBatteryKw('-5', '48')).toBeNull()
        expect(effectiveBatteryKw('abc', '48')).toBeNull()
    })

    it('falls back to the default voltage when unset or invalid', () => {
        expect(DEFAULT_BATTERY_VOLTAGE_V).toBe(48)
        expect(effectiveBatteryKw('100', '')).toBe('~4.80 kW at 48 V')
        expect(effectiveBatteryKw('100', undefined)).toBe('~4.80 kW at 48 V')
        expect(effectiveBatteryKw('100', '0')).toBe('~4.80 kW at 48 V')
    })
})
