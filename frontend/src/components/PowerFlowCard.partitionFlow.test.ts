import { describe, expect, it } from 'vitest'
import { cxFor, exitYFor, partitionFlow, toPathD } from './PowerFlowCard'
import type { PowerFlowData } from './PowerFlowRegistry'

const baseData: PowerFlowData = {
    solar: { kw: 0 },
    battery: { kw: 0, soc: 50 },
    grid: { kw: 0 },
    house: { kw: 1 },
    water: { kw: 0 },
}

describe('partitionFlow', () => {
    it('excludes battery from sources and loads when battery is not in enabledIds, even with nonzero kw', () => {
        const enabledIds = new Set(['solar', 'grid', 'house'])
        const data: PowerFlowData = { ...baseData, battery: { kw: 3, soc: 60 } }
        const { sources, loads } = partitionFlow(data, enabledIds)
        expect(sources.find((s) => s.id === 'battery')).toBeUndefined()
        expect(loads.find((l) => l.id === 'battery')).toBeUndefined()
    })

    it('does not crash and omits the EV node when data.ev is undefined', () => {
        const enabledIds = new Set(['solar', 'battery', 'grid', 'house', 'water', 'ev'])
        const data: PowerFlowData = { ...baseData, ev: undefined }
        expect(() => partitionFlow(data, enabledIds)).not.toThrow()
        const { sources, loads } = partitionFlow(data, enabledIds)
        expect(sources.find((s) => s.id === 'ev')).toBeUndefined()
        expect(loads.find((l) => l.id === 'ev')).toBeUndefined()
    })

    it('routes a negative grid.kw (export) to loads, not sources', () => {
        const enabledIds = new Set(['solar', 'battery', 'grid', 'house', 'water'])
        const data: PowerFlowData = { ...baseData, grid: { kw: -2.5 } }
        const { sources, loads } = partitionFlow(data, enabledIds)
        expect(sources.find((s) => s.id === 'grid')).toBeUndefined()
        const gridLoad = loads.find((l) => l.id === 'grid')
        expect(gridLoad).toBeDefined()
        expect(gridLoad?.kw).toBeCloseTo(2.5)
    })
})

describe('toPathD', () => {
    it('returns an empty string for no points', () => {
        expect(toPathD([])).toBe('')
    })

    it('produces a well-formed M/L path string', () => {
        const d = toPathD([
            { x: 0, y: 0 },
            { x: 10, y: 5 },
            { x: 20, y: 10 },
        ])
        expect(d).toBe('M 0 0 L 10 5 L 20 10')
        expect(d).toMatch(/^M [\d.-]+ [\d.-]+( L [\d.-]+ [\d.-]+)*$/)
    })
})

describe('cxFor / exitYFor', () => {
    it('spreads points evenly across the span', () => {
        const count = 3
        const xs = [0, 1, 2].map((i) => cxFor(i, count))
        expect(xs[0]).toBeLessThan(xs[1])
        expect(xs[1]).toBeLessThan(xs[2])
    })

    it('returns distinct exit Y values for top vs bottom rows', () => {
        expect(exitYFor('top')).not.toBe(exitYFor('bot'))
    })
})
