import { describe, expect, it } from 'vitest'
import {
    buildSlotInfo,
    formatKw,
    formatPercent,
    formatRangeFromLabel,
    formatTimeRange,
    buildCompactLine,
    estimatedRanges,
    isEstimatedSlot,
    phaseBadge,
    splitActualPlan,
    plannedActionText,
    priceAxisMax,
    slotMarkKinds,
    slotPhase,
    slotTimeRange,
    type SlotSeries,
} from './ChartCard.logic'

const labels = ['10:00', '10:15', '10:30', '10:45']

function makeSeries(overrides: Partial<SlotSeries> = {}): SlotSeries {
    return {
        labels,
        resolutionMinutes: 15,
        nowIndex: 2,
        price: [1.1, 1.2, 1.3, 1.4],
        pv: [1, 2, 3, 4],
        load: [0.5, 0.6, 0.7, 0.8],
        charge: [null, null, 3.2, null],
        discharge: [null, null, null, 2],
        export: [null, null, null, null],
        socProjected: [50, 52, 55, 54],
        ...overrides,
    }
}

describe('time formatting', () => {
    it('formats a slot as a 24h range, never AM/PM', () => {
        // 12:15Z is 14:15 in Stockholm (CEST)
        expect(formatTimeRange('2026-07-15T12:15:00Z', 15)).toBe('14:15–14:30')
        expect(formatTimeRange('2026-07-15T21:45:00Z', 15)).toBe('23:45–00:00')
        expect(formatTimeRange('2026-07-15T12:15:00Z', 15)).not.toMatch(/am|pm/i)
    })

    it('returns an empty string for an invalid ISO time', () => {
        expect(formatTimeRange('nope', 15)).toBe('')
    })

    it('builds a range from an HH:MM label and wraps at midnight', () => {
        expect(formatRangeFromLabel('14:15', 15)).toBe('14:15–14:30')
        expect(formatRangeFromLabel('23:45', 15)).toBe('23:45–00:00')
        expect(formatRangeFromLabel('08:00', 60)).toBe('08:00–09:00')
    })

    it('prefers slot start times and falls back to the label', () => {
        const withStarts = makeSeries({ slotStarts: ['2026-07-15T08:00:00Z', '', '', ''] })
        expect(slotTimeRange(withStarts, 0)).toBe('10:00–10:15')
        expect(slotTimeRange(makeSeries(), 1)).toBe('10:15–10:30')
    })
})

describe('value formatting', () => {
    it('formats kW and percent, with a dash for missing values', () => {
        expect(formatKw(3.24)).toBe('3.2 kW')
        expect(formatKw(0)).toBe('0.0 kW')
        expect(formatKw(null)).toBe('—')
        expect(formatPercent(54.6)).toBe('55 %')
        expect(formatPercent(undefined)).toBe('—')
    })
})

describe('past / future split', () => {
    it('classifies slots around now', () => {
        expect(slotPhase(1, 2)).toBe('past')
        expect(slotPhase(2, 2)).toBe('now')
        expect(slotPhase(3, 2)).toBe('future')
        expect(slotPhase(0, null)).toBe('future')
    })

    it('keeps measured values up to now and drops later ones', () => {
        expect(splitActualPlan([1, 2, 3, 4], 2)).toEqual([1, 2, 3, null])
        expect(splitActualPlan([1, null, 3, 4], 1)).toEqual([1, null, null, null])
    })

    it('leaves the series alone when there is no now in view', () => {
        const actual = [1, 2, 3]
        expect(splitActualPlan(actual, null)).toBe(actual)
        expect(splitActualPlan(actual, undefined)).toBe(actual)
    })
})

describe('estimated prices', () => {
    it('flags only forecast-priced slots', () => {
        expect(isEstimatedSlot({ price_source: 'forecast' })).toBe(true)
        expect(isEstimatedSlot({ price_source: 'nordpool' })).toBe(false)
        expect(isEstimatedSlot({})).toBe(false)
    })

    it('finds runs of consecutive estimated slots', () => {
        expect(estimatedRanges([false, true, true, false, true])).toEqual([
            { from: 1, to: 2 },
            { from: 4, to: 4 },
        ])
        expect(estimatedRanges([null, null])).toEqual([])
        expect(estimatedRanges(undefined)).toEqual([])
    })

    it('shows Estimated instead of Plan or Now, but never for past slots', () => {
        expect(phaseBadge('future', true)).toBe('Estimated')
        expect(phaseBadge('future', false)).toBe('Plan')
        expect(phaseBadge('now', false)).toBe('Now')
        expect(phaseBadge('past', true)).toBe('Past')
    })

    it('carries the flag into the info panel and compact line', () => {
        const series = makeSeries({ estimated: [false, false, false, true] })
        expect(buildSlotInfo(series, 3)?.estimated).toBe(true)
        expect(buildSlotInfo(series, 2)?.estimated).toBe(false)
        expect(buildCompactLine(series, 3)?.badge).toBe('Estimated')
    })
})

describe('compact line', () => {
    it('summarises the planned slot in one line', () => {
        const line = buildCompactLine(makeSeries({ socProjected: [50, 52, 64, 54] }), 2)
        expect(line?.range).toBe('10:30–10:45')
        expect(line?.badge).toBe('Now')
        expect(line?.parts.join(' · ')).toBe('Charge 3.2 kW · 1.30 kr/kWh · SoC 64% · PV 3.0 kW · Load 0.7 kW')
    })

    it('shows measured values for past slots and Hold when idle', () => {
        const series = makeSeries({
            socActual: [48, 49, null, null],
            actualPv: [1.5, null, null, null],
            actualLoad: [0.4, null, null, null],
            actualCharge: [0, null, null, null],
        })
        const line = buildCompactLine(series, 0)
        expect(line?.badge).toBe('Past')
        expect(line?.parts).toEqual(['Hold', '1.10 kr/kWh', 'SoC 48%', 'PV 1.5 kW', 'Load 0.4 kW'])
    })

    it('omits missing values and rejects out-of-range slots', () => {
        const line = buildCompactLine(makeSeries({ price: [], socProjected: [] }), 3)
        expect(line?.parts.some((p) => p.startsWith('SoC') || p.includes('kr'))).toBe(false)
        expect(buildCompactLine(makeSeries(), 9)).toBeNull()
    })
})

describe('slotMarkKinds', () => {
    it('marks every active planned action in strip order', () => {
        const planned = { charge: [3, null], discharge: [null, 2], export: [0.01, 1], water: [1, 1] }
        expect(slotMarkKinds(0, null, planned)).toEqual(['charge', 'water'])
        expect(slotMarkKinds(1, null, planned)).toEqual(['discharge', 'export', 'water'])
    })

    it('uses the measured value instead of the plan before now', () => {
        const planned = { charge: [3, 3] }
        const actual = { charge: [null, 0] }
        expect(slotMarkKinds(0, 5, planned, actual)).toEqual(['charge']) // no measurement: plan stays
        expect(slotMarkKinds(1, 5, planned, actual)).toEqual([]) // measured idle beats the plan
        expect(slotMarkKinds(1, 0, planned, actual)).toEqual(['charge']) // future: plan
    })

    it('skips hidden (absent) series and lets water boost replace plain water', () => {
        expect(slotMarkKinds(0, null, { water: [1], waterBoost: [1] })).toEqual(['waterBoost'])
        expect(slotMarkKinds(0, null, {})).toEqual([])
    })
})

describe('plannedActionText', () => {
    it('describes the plan for a slot', () => {
        const series = makeSeries({ water: [null, null, 1, null], export: [null, null, 1.5, null] })
        expect(plannedActionText(series, 2)).toBe('Charge battery 3.2 kW · Export 1.5 kW · Heat water')
        expect(plannedActionText(series, 3)).toBe('Discharge battery 2.0 kW')
        expect(plannedActionText(series, 0)).toBe('Hold · self-use')
    })
})

describe('buildSlotInfo', () => {
    it('returns null for an index outside the data', () => {
        expect(buildSlotInfo(makeSeries(), 9)).toBeNull()
        expect(buildSlotInfo(makeSeries(), -1)).toBeNull()
    })

    it('groups price, battery and energy with the planned values for a future slot', () => {
        const info = buildSlotInfo(makeSeries({ gridImport: [0, 0, 0, 1.5] }), 3, {
            breakdown: { spot: 0.9, feesAndVat: 0.5 },
        })
        expect(info?.phase).toBe('future')
        expect(info?.range).toBe('10:45–11:00')
        expect(info?.groups.map((g) => g.title)).toEqual(['Price', 'Battery', 'Energy'])
        const [price, battery, energy] = info?.groups ?? []
        expect(price.rows[0].value).toBe('1.40 SEK/kWh')
        expect(price.note).toBe('Spot 0.90 + fees 0.50')
        expect(battery.rows.map((r) => [r.label, r.value])).toEqual([
            ['SoC', '54 %'],
            ['Charge', '—'],
            ['Discharge', '2.0 kW'],
        ])
        expect(energy.rows.map((r) => [r.label, r.value])).toEqual([
            ['PV', '4.0 kW'],
            ['Load', '0.8 kW'],
            ['Grid import', '1.5 kW'],
            ['Grid export', '—'],
        ])
        expect(energy.rows.every((r) => r.plan === undefined)).toBe(true)
    })

    it('leads with the measurement and keeps the plan beside it for a past slot', () => {
        const series = makeSeries({ actualPv: [2.5, 2.5, null, null], socActual: [49, 51, null, null] })
        const info = buildSlotInfo(series, 1)
        expect(info?.phase).toBe('past')
        const rows = Object.fromEntries((info?.groups ?? []).flatMap((g) => g.rows).map((r) => [r.key, r]))
        expect(rows.pv.value).toBe('2.5 kW')
        expect(rows.pv.plan).toBe('2.0 kW')
        expect(rows.soc.value).toBe('51 %')
        expect(rows.soc.plan).toBe('52 %')
        // no measurement for load: planned value, no ghost
        expect(rows.load.value).toBe('0.6 kW')
        expect(rows.load.plan).toBeUndefined()
    })

    it('adds a Loads group only when water or EV is active', () => {
        expect(buildSlotInfo(makeSeries(), 0)?.groups.map((g) => g.title)).not.toContain('Loads')
        const series = makeSeries({ water: [1.5, null, null, null], evCharging: [null, 7, null, null] })
        const water = buildSlotInfo(series, 0)?.groups.find((g) => g.title === 'Loads')
        expect(water?.rows.map((r) => [r.label, r.value])).toEqual([['Water heating', '1.5 kW']])
        const ev = buildSlotInfo(series, 1)?.groups.find((g) => g.title === 'Loads')
        expect(ev?.rows.map((r) => [r.label, r.value])).toEqual([['EV charging', '7.0 kW']])
    })
})

describe('priceAxisMax', () => {
    it('doubles the data maximum so the area stays in the lower half', () => {
        expect(priceAxisMax(2.5)).toBe(5)
    })
    it('falls back to 1 without usable data', () => {
        expect(priceAxisMax(0)).toBe(1)
        expect(priceAxisMax(Number.NaN)).toBe(1)
    })
})
