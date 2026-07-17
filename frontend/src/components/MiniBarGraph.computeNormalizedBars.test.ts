import { describe, expect, it } from 'vitest'
import { computeNormalizedBars } from './MiniBarGraph'

describe('computeNormalizedBars', () => {
    it('returns a flat fallback of `bars` length for empty data', () => {
        const result = computeNormalizedBars([], 12)
        expect(result).toHaveLength(12)
        expect(result.every((v) => v === 0.2)).toBe(true)
    })

    it('normalizes all-equal values without producing NaN or Infinity', () => {
        const result = computeNormalizedBars([5, 5, 5], 12)
        expect(result).toHaveLength(3)
        for (const v of result) {
            expect(Number.isFinite(v)).toBe(true)
        }
    })

    it('does not pad when there are fewer points than `bars`', () => {
        const result = computeNormalizedBars([1, 2, 3], 12)
        expect(result).toHaveLength(3)
    })

    it('normalizes negative values into the 0.1-1.0 range', () => {
        const result = computeNormalizedBars([-10, 0, 10], 12)
        expect(result).toHaveLength(3)
        expect(result[0]).toBeCloseTo(0.1) // min -> 0.1
        expect(result[2]).toBeCloseTo(1.0) // max -> 1.0
        for (const v of result) {
            expect(v).toBeGreaterThanOrEqual(0.1)
            expect(v).toBeLessThanOrEqual(1.0)
        }
    })
})
