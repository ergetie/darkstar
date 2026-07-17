import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildLiveData } from './ChartCard'
import type { ScheduleSlot } from '../lib/types'

afterEach(() => {
    vi.useRealTimers()
})

function dsByLabel(data: ReturnType<typeof buildLiveData>, label: string) {
    const ds = data?.datasets.find((d) => (d as { label?: string }).label === label)
    if (!ds) throw new Error(`dataset "${label}" not found`)
    return ds
}

function makeSlot(startTime: string, overrides: Partial<ScheduleSlot> = {}): ScheduleSlot {
    return { start_time: startTime, ...overrides }
}

describe('buildLiveData', () => {
    it('builds 192 15-min buckets over 48h with correct labels and nowIndex', () => {
        vi.setSystemTime(new Date('2026-07-15T10:07:00Z'))
        const slots: ScheduleSlot[] = []
        // today 00:00Z through the next 48h at 15-min resolution
        for (let i = 0; i < 96; i++) {
            const t = new Date(Date.UTC(2026, 6, 15, 0, 0, 0) + i * 15 * 60 * 1000)
            slots.push(makeSlot(t.toISOString(), { import_price_sek_kwh: 1.5 }))
        }
        const result = buildLiveData(slots, 'today')
        expect(result).not.toBeNull()
        // 48h at 15-min resolution = 192 buckets
        expect(result?.labels?.length).toBe(192)
        expect(result?.hasNoData).toBe(false)
        // 10:07 UTC falls in the bucket starting at 10:00 UTC -> index 40
        expect(result?.nowIndex).toBe(40)
    })

    it('produces null battery series without NaN when slots have no battery fields', () => {
        vi.setSystemTime(new Date('2026-07-15T10:00:00Z'))
        const slots: ScheduleSlot[] = [
            makeSlot('2026-07-15T00:00:00Z', { import_price_sek_kwh: 1.0 }),
            makeSlot('2026-07-15T00:15:00Z', { import_price_sek_kwh: 1.1 }),
        ]
        const result = buildLiveData(slots, 'today')
        const charge = dsByLabel(result, 'Charge (kW)').data as (number | null)[]
        const discharge = dsByLabel(result, 'Discharge (kW)').data as (number | null)[]
        for (const v of [...charge, ...discharge]) {
            expect(v === null || Number.isFinite(v)).toBe(true)
            expect(Number.isNaN(v)).toBe(false)
        }
        // the two provided slots occupy indices 0 and 1; both are battery-less -> null
        expect(charge[0]).toBeNull()
        expect(discharge[0]).toBeNull()
    })

    it('produces null EV series without throwing when slots have no EV fields', () => {
        vi.setSystemTime(new Date('2026-07-15T10:00:00Z'))
        const slots: ScheduleSlot[] = [makeSlot('2026-07-15T00:00:00Z', { import_price_sek_kwh: 1.0 })]
        expect(() => buildLiveData(slots, 'today')).not.toThrow()
        const result = buildLiveData(slots, 'today')
        const evCharging = dsByLabel(result, 'EV Charging (kW)').data as (number | null)[]
        const evSurplus = dsByLabel(result, 'EV Surplus Charging (kW)').data as (number | null)[]
        expect(evCharging[0]).toBeNull()
        expect(evSurplus[0]).toBeNull()
    })

    it('falls back to hasNoData when there are no slots for today/tomorrow', () => {
        vi.setSystemTime(new Date('2026-07-15T10:00:00Z'))
        const result = buildLiveData([], 'today')
        expect(result?.hasNoData).toBe(true)
        expect(result?.labels?.length).toBe(48)
    })

    it('sums a multi-charger ev_surplus_kw dict, and treats an empty dict as 0', () => {
        vi.setSystemTime(new Date('2026-07-15T10:00:00Z'))
        const slots: ScheduleSlot[] = [
            makeSlot('2026-07-15T00:00:00Z', {
                import_price_sek_kwh: 1.0,
                ev_surplus_kw: { charger_a: 1.2, charger_b: 0.5 },
            }),
            makeSlot('2026-07-15T00:15:00Z', {
                import_price_sek_kwh: 1.0,
                ev_surplus_kw: {},
            }),
        ]
        const result = buildLiveData(slots, 'today')
        const evSurplus = dsByLabel(result, 'EV Surplus Charging (kW)').data as (number | null)[]
        expect(evSurplus[0]).toBeCloseTo(1.7)
        expect(evSurplus[1]).toBeNull() // 0 total is below the 0.01 display threshold -> null
    })
})
