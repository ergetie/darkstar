import { Zap } from 'lucide-react'
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

describe('EV accessors (via deriveEvNodeView)', () => {
    it('returns undefined when there are zero chargers', () => {
        const ev = node('ev')
        expect(ev.subValueAccessor?.({ ...baseData, evChargers: [] })).toBeUndefined()
        expect(ev.subValueAccessor?.({ ...baseData })).toBeUndefined()
    })

    it('single charging charger shows SoC → target and the lightning icon', () => {
        const ev = node('ev')
        const data: PowerFlowData = {
            ...baseData,
            evChargers: [{ id: 'ev1', name: 'A', kw: 7.2, soc: 49, pluggedIn: true }],
            evChargerStatuses: [{ id: 'ev1', name: 'A', target_soc_percent: 80, manual_charge: null }],
        }
        expect(ev.subValueAccessor?.(data)).toBe('49% → 80%')
        expect(typeof ev.lucideIcon === 'function' ? ev.lucideIcon(data) : null).toBe(Zap)
    })

    it('multiple chargers show the connected count', () => {
        const ev = node('ev')
        const result = ev.subValueAccessor?.({
            ...baseData,
            evChargers: [
                { id: 'a', name: 'A', kw: 0, soc: 42, pluggedIn: false },
                { id: 'b', name: 'B', kw: 3, soc: 77, pluggedIn: true },
            ],
        })
        expect(result).toBe('1 connected')
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
