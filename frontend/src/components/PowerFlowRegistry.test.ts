import { describe, expect, it } from 'vitest'
import { NODE_REGISTRY } from './PowerFlowRegistry'
import type { PowerFlowData } from './PowerFlowRegistry'

const baseData: PowerFlowData = {
    solar: { kw: 0 },
    battery: { kw: 0, soc: 50 },
    grid: { kw: 0 },
    house: { kw: 0 },
    water: { kw: 0 },
}

function node(id: string) {
    const n = NODE_REGISTRY.find((n) => n.id === id)
    if (!n) throw new Error(`node ${id} not found in registry`)
    return n
}

describe('fmtKw (via node valueAccessors)', () => {
    it('switches to 2 decimal places just below the 0.1 boundary', () => {
        const solar = node('solar')
        expect(solar.valueAccessor({ ...baseData, solar: { kw: 0.099 } })).toBe('0.10 kW')
    })

    it('uses 1 decimal place at and above the 0.1 boundary', () => {
        const solar = node('solar')
        expect(solar.valueAccessor({ ...baseData, solar: { kw: 0.1 } })).toBe('0.1 kW')
    })

    it('uses 1 decimal place at exactly zero', () => {
        const solar = node('solar')
        expect(solar.valueAccessor({ ...baseData, solar: { kw: 0 } })).toBe('0.0 kW')
    })
})

describe('EV subValueAccessor', () => {
    it('returns undefined when there are zero chargers', () => {
        const ev = node('ev')
        expect(ev.subValueAccessor?.({ ...baseData, evChargers: [] })).toBeUndefined()
        expect(ev.subValueAccessor?.({ ...baseData })).toBeUndefined()
    })

    it('falls back to the first charger when multiple chargers exist and none are plugged in', () => {
        const ev = node('ev')
        const result = ev.subValueAccessor?.({
            ...baseData,
            evChargers: [
                { name: 'A', kw: 0, soc: 42, pluggedIn: false },
                { name: 'B', kw: 0, soc: 77, pluggedIn: false },
            ],
        })
        expect(result).toBe('42%')
    })

    it('prefers the plugged-in charger when one exists among several', () => {
        const ev = node('ev')
        const result = ev.subValueAccessor?.({
            ...baseData,
            evChargers: [
                { name: 'A', kw: 0, soc: 42, pluggedIn: false },
                { name: 'B', kw: 3, soc: 77, pluggedIn: true },
            ],
        })
        expect(result).toBe('77%')
    })
})

describe('battery label', () => {
    it('flips from Charge to Discharge exactly at kw === 0', () => {
        const battery = node('battery')
        expect(
            typeof battery.label === 'function' ? battery.label({ ...baseData, battery: { kw: 0, soc: 50 } }) : null,
        ).toBe('Charge')
        expect(
            typeof battery.label === 'function' ? battery.label({ ...baseData, battery: { kw: 0.01, soc: 50 } }) : null,
        ).toBe('Discharge')
        expect(
            typeof battery.label === 'function'
                ? battery.label({ ...baseData, battery: { kw: -0.01, soc: 50 } })
                : null,
        ).toBe('Charge')
    })
})
