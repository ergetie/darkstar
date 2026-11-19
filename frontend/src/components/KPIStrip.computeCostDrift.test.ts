import { describe, expect, it } from 'vitest'
import { computeCostDrift } from './KPIStrip'

describe('computeCostDrift', () => {
    it('returns zero drift labeled as saved for an undefined series', () => {
        const result = computeCostDrift(undefined, 'SEK')
        expect(result.costDrift).toBe(0)
        expect(result.isSaving).toBe(true)
        expect(result.costDriftLabel).toBe('Saved 0.0 SEK')
    })

    it('returns zero drift labeled as saved for an empty series', () => {
        const result = computeCostDrift([])
        expect(result.costDrift).toBe(0)
        expect(result.isSaving).toBe(true)
    })

    it('labels as Overspent when realized costs exceed planned', () => {
        const result = computeCostDrift([{ date: '2026-07-14', planned: 10, realized: 15 }], 'SEK')
        expect(result.costDrift).toBeCloseTo(5)
        expect(result.isSaving).toBe(false)
        expect(result.costDriftLabel).toBe('Overspent 5.0 SEK')
    })

    it('treats exact zero drift as saved (boundary)', () => {
        const result = computeCostDrift([{ date: '2026-07-14', planned: 10, realized: 10 }], 'SEK')
        expect(result.costDrift).toBe(0)
        expect(result.isSaving).toBe(true)
        expect(result.costDriftLabel).toBe('Saved 0.0 SEK')
    })

    it('uses the configured currency', () => {
        const series = [{ date: '2026-07-14', planned: 10, realized: 15 }]
        expect(computeCostDrift(series, 'EUR').costDriftLabel).toBe('Overspent 5.0 EUR')
    })

    it('shows no unit before the currency is known', () => {
        const series = [{ date: '2026-07-14', planned: 10, realized: 15 }]
        expect(computeCostDrift(series).costDriftLabel).toBe('Overspent 5.0')
    })
})
