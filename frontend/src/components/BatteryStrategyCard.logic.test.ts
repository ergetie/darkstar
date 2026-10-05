import { describe, expect, it } from 'vitest'
import {
    computeFloorBreakdown,
    computeSocContextMessage,
    computeSparklineBars,
    SPARKLINE_MIN_BAR_PERCENT,
    describePriceReserve,
} from './BatteryStrategyCard'
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

describe('computeSparklineBars', () => {
    it('gives a single-day outlook a finite, visible bar (min === max)', () => {
        const result = computeSparklineBars([1.5])
        expect(result.range).toBe(1) // guarded fallback, not 0
        expect(result.heights).toHaveLength(1)
        expect(result.heights[0]).toBeGreaterThanOrEqual(SPARKLINE_MIN_BAR_PERCENT)
        expect(Number.isFinite(result.heights[0])).toBe(true)
    })

    it('scales the cheapest day to the minimum and the dearest to 100%', () => {
        const result = computeSparklineBars([1, 2, 3])
        expect(result.minPrice).toBe(1)
        expect(result.maxPrice).toBe(3)
        expect(result.range).toBe(2)
        expect(result.heights[0]).toBe(SPARKLINE_MIN_BAR_PERCENT)
        expect(result.heights[2]).toBe(100)
        expect(result.heights[1]).toBeCloseTo((SPARKLINE_MIN_BAR_PERCENT + 100) / 2)
    })

    it('places the reference line on the bar scale and clamps it', () => {
        expect(computeSparklineBars([1, 3], 2).refPercent).toBeCloseTo((SPARKLINE_MIN_BAR_PERCENT + 100) / 2)
        expect(computeSparklineBars([1, 3], 10).refPercent).toBe(100)
        expect(computeSparklineBars([1, 3], -5).refPercent).toBe(SPARKLINE_MIN_BAR_PERCENT)
        expect(computeSparklineBars([1, 3], null).refPercent).toBeNull()
    })

    it('handles an empty series', () => {
        expect(computeSparklineBars([]).heights).toEqual([])
    })
})

describe('computeFloorBreakdown', () => {
    it('uses the capped deficit and the price reserve on top of it', () => {
        const b = computeFloorBreakdown(
            {
                min_soc_kwh: 4,
                base_reserve_kwh: 20.1,
                effective_reserve_kwh: 20.1,
                weather_buffer_kwh: 0.5,
                calculated_floor_kwh: 9.4,
                final_floor_kwh: 16.6,
            },
            30,
        )
        const kwh = Object.fromEntries(b!.zones.map((z) => [z.key, z.kwh]))
        expect(kwh.min).toBe(4)
        expect(kwh.deficit).toBeCloseTo(5.4)
        expect(kwh.weather).toBeCloseTo(0)
        expect(kwh.price).toBeCloseTo(7.2)
        expect(kwh.tradable).toBeCloseTo(13.4)
        expect(b!.floorKwh).toBe(16.6)
    })

    it('falls back to the deficit floor when final_floor_kwh is missing', () => {
        const b = computeFloorBreakdown(
            { min_soc_kwh: 2, base_reserve_kwh: 1, weather_buffer_kwh: 1, calculated_floor_kwh: 4 },
            10,
        )
        expect(b!.floorKwh).toBe(4)
        expect(b!.zones.find((z) => z.key === 'price')!.kwh).toBe(0)
        expect(b!.zones.find((z) => z.key === 'weather')!.kwh).toBe(1)
    })

    it('returns null without floor data', () => {
        expect(computeFloorBreakdown(undefined, 10)).toBeNull()
    })
})

describe('describePriceReserve', () => {
    const base = {
        unseen_window_start: '2026-10-06T00:00:00+02:00',
        known_cost_sek_kwh: 0.8,
        own_day_cost_sek_kwh: 1.4,
    }

    it('explains an active reserve with both costs', () => {
        const r = describePriceReserve({ ...base, price_reserve_reason: 'active', price_reserve_applied_kwh: 7.2 })
        expect(r!.title).toBe('Holding 7.2 kWh extra for Tuesday')
        expect(r!.detail).toBe('Cheaper to store it: charging now ~80 öre vs ~140 öre on Tuesday')
    })

    it('explains why the reserve is inactive', () => {
        expect(describePriceReserve({ ...base, price_reserve_reason: 'own_day_cheaper' })!.title).toBe(
            'No extra reserve: Tuesday looks cheaper to charge',
        )
        expect(describePriceReserve({ price_reserve_reason: 'disabled' })!.title).toBe('Price reserve is turned off')
    })

    it('returns null when the planner sent no reason', () => {
        expect(describePriceReserve({})).toBeNull()
    })
})
