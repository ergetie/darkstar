import { describe, expect, it } from 'vitest'
import { computeTodaySummary } from './Dashboard'
import type { ScheduleSlot } from '../lib/types'

const now = new Date('2026-07-15T12:00:00')

function slot(hhmm: string, overrides: Partial<ScheduleSlot> = {}): ScheduleSlot {
    return { start_time: `2026-07-15T${hhmm}:00`, ...overrides }
}

describe('computeTodaySummary', () => {
    it('returns null when there are no slots at all', () => {
        expect(computeTodaySummary([], now)).toBeNull()
    })

    it('returns null when no slots fall within today', () => {
        const slots = [slot('00:00', { export_kwh: 1, start_time: '2026-07-16T00:00:00' })]
        expect(computeTodaySummary(slots, now)).toBeNull()
    })

    it('produces only Export phases for battery-less slots with only export activity', () => {
        const slots = [
            slot('06:00', { export_kwh: 1.5, import_price_sek_kwh: 0.5 }),
            slot('06:30', { export_kwh: 1.2, import_price_sek_kwh: 0.5 }),
        ]
        const summary = computeTodaySummary(slots, now)
        expect(summary).toMatch(/^Export /)
        expect(summary).not.toMatch(/Charge|Discharge/)
    })

    it('merges adjacent same-action slots into a single range', () => {
        const slots = [
            slot('00:00', { charge_kw: 2 }),
            slot('00:30', { charge_kw: 2 }),
            slot('01:00', { charge_kw: 2 }),
        ]
        const summary = computeTodaySummary(slots, now)
        // 3 consecutive 30-min charge slots merge into a single 00:00-01:30 range.
        expect(summary).toBe('Charge 00:00-01:30')
        expect(summary?.match(/Charge/g)?.length).toBe(1)
    })

    it('joins Charge -> Discharge -> Export phases in chronological order', () => {
        const slots = [
            slot('00:00', { charge_kw: 2 }),
            slot('06:00', { discharge_kw: 2 }),
            slot('18:00', { export_kwh: 1.5 }),
        ]
        const summary = computeTodaySummary(slots, now)
        const order = summary?.split(' → ').map((p) => p.split(' ')[0])
        expect(order).toEqual(['Charge', 'Discharge', 'Export'])
    })
})
