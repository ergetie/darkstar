import { describe, expect, it } from 'vitest'
import { computeHouseKw } from './PowerFlowHouse'

const both = new Set(['house', 'ev', 'water'])

describe('computeHouseKw', () => {
    it('subtracts both EV and water loads', () => {
        expect(computeHouseKw(8.0, 6.9, 0.2, both)).toBeCloseTo(0.9)
    })

    it('does not subtract EV when the EV node is disabled', () => {
        expect(computeHouseKw(8.0, 6.9, 0.2, new Set(['house', 'water']))).toBeCloseTo(7.8)
    })

    it('does not subtract water when the water node is disabled', () => {
        expect(computeHouseKw(8.0, 6.9, 0.2, new Set(['house', 'ev']))).toBeCloseTo(1.1)
    })

    it('clamps a negative residual to 0', () => {
        expect(computeHouseKw(3.0, 6.9, 0.2, both)).toBe(0)
    })

    it('treats missing inputs as 0', () => {
        expect(computeHouseKw(2.5, undefined, null, both)).toBeCloseTo(2.5)
        expect(computeHouseKw(undefined, 1.0, 0.5, both)).toBe(0)
        expect(computeHouseKw(null, null, null, both)).toBe(0)
    })
})
