import { describe, expect, it } from 'vitest'
import { splitPriceBreakdown } from './ChartCard'

describe('splitPriceBreakdown', () => {
    it('splits spot and feesAndVat so they sum back to the input value', () => {
        const value = 2.5
        const pricing = { vat: 25, fees: 0.3 }
        const result = splitPriceBreakdown(value, pricing)
        expect(result).not.toBeNull()
        expect(result!.spot + result!.feesAndVat).toBeCloseTo(value)
    })

    it('falls back to the raw value (no division) when vat = -100 would zero the divisor', () => {
        const value = 2.5
        const pricing = { vat: -100, fees: 0.3 }
        const result = splitPriceBreakdown(value, pricing)
        expect(result).not.toBeNull()
        expect(Number.isFinite(result!.spot)).toBe(true)
        expect(Number.isFinite(result!.feesAndVat)).toBe(true)
        // basePrice falls back to `value` itself when vatMul <= 0
        expect(result!.spot).toBeCloseTo(Math.max(0, value - pricing.fees))
    })

    it('returns null when pricing is undefined', () => {
        expect(splitPriceBreakdown(2.5, undefined)).toBeNull()
    })

    it('clamps spot to 0 when fees exceed the base price', () => {
        const value = 0.1
        const pricing = { vat: 0, fees: 5 }
        const result = splitPriceBreakdown(value, pricing)
        expect(result!.spot).toBe(0)
        expect(result!.feesAndVat).toBeCloseTo(value)
    })
})
