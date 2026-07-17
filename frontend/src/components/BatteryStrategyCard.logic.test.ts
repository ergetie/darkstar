import { describe, expect, it } from 'vitest'
import { computeSocContextMessage, computeSparklineRange } from './BatteryStrategyCard'
import type { PriceOutlookDay, PriceOutlookResponse } from '../lib/api'

function makeDay(overrides: Partial<PriceOutlookDay> = {}): PriceOutlookDay {
    return {
        date: '2026-07-15',
        day_label: 'Mon',
        days_ahead: 0,
        avg_spot_p50: 1.0,
        avg_spot_p10: null,
        avg_spot_p90: null,
        min_hour_p50: 0,
        max_hour_p50: 12,
        level: 'normal',
        confidence: 'high',
        ...overrides,
    }
}

function makeOutlook(days: PriceOutlookDay[]): PriceOutlookResponse {
    return { enabled: true, days, reference_avg: null, status: 'ok' }
}

describe('computeSocContextMessage', () => {
    it('reports "charging ahead of cheap D{n}" when a single cheap day exists', () => {
        const priceOutlook = makeOutlook([
            makeDay({ level: 'normal' }),
            makeDay({ level: 'cheap' }), // day index 1 -> D2
            makeDay({ level: 'normal' }),
        ])
        const msg = computeSocContextMessage({ currentAction: 'Charge', soc: 30, socTarget: 80, priceOutlook })
        expect(msg).toBe('charging ahead of cheap D2')
    })

    it('reports "charging ahead of cheap D{n}→D{m}" for a cheap-day range', () => {
        const priceOutlook = makeOutlook([
            makeDay({ level: 'cheap' }), // D1
            makeDay({ level: 'cheap' }), // D2
            makeDay({ level: 'cheap' }), // D3
            makeDay({ level: 'normal' }),
        ])
        const msg = computeSocContextMessage({ currentAction: 'Charge', soc: 30, socTarget: 80, priceOutlook })
        expect(msg).toBe('charging ahead of cheap D1→D3')
    })

    it('falls back to plain "charging" when priceOutlook is undefined, without crashing', () => {
        expect(() =>
            computeSocContextMessage({ currentAction: 'Charge', soc: 30, socTarget: 80, priceOutlook: undefined }),
        ).not.toThrow()
        const msg = computeSocContextMessage({
            currentAction: 'Charge',
            soc: 30,
            socTarget: 80,
            priceOutlook: undefined,
        })
        expect(msg).toBe('charging')
    })

    it('returns null when there is no current action', () => {
        expect(
            computeSocContextMessage({ currentAction: undefined, soc: 30, socTarget: 80, priceOutlook: undefined }),
        ).toBeNull()
    })
})

describe('computeSparklineRange', () => {
    it('guards the div-by-zero case for a single-day outlook (min === max)', () => {
        const result = computeSparklineRange([1.5])
        expect(result.minPrice).toBe(1.5)
        expect(result.maxPrice).toBe(1.5)
        expect(result.range).toBe(1) // guarded fallback, not 0
        expect(Number.isFinite(result.maxTopPercent)).toBe(true)
    })

    it('computes min/max/range for a normal multi-day series', () => {
        const result = computeSparklineRange([1, 2, 3])
        expect(result.minPrice).toBe(1)
        expect(result.maxPrice).toBe(3)
        expect(result.range).toBe(2)
    })
})
