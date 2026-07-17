import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseLocalISODate, toLocalISODate, tomorrowLocalISODate } from './EVChargingCard'

afterEach(() => {
    vi.useRealTimers()
})

describe('toLocalISODate / parseLocalISODate', () => {
    it('round-trips a date near a UTC-offset day boundary (local day differs from UTC day)', () => {
        // 2026-07-15T22:30:00Z is 2026-07-16T00:30 in Stockholm (summer, UTC+2) —
        // the UTC calendar day is still the 15th while the local day is the 16th.
        // A naive toISOString().slice(0, 10) would wrongly report the 15th.
        const d = new Date('2026-07-15T22:30:00Z')
        const iso = toLocalISODate(d)
        expect(iso).toBe('2026-07-16')

        const parsed = parseLocalISODate(iso)
        expect(toLocalISODate(parsed)).toBe(iso)
        expect(parsed.getFullYear()).toBe(2026)
        expect(parsed.getMonth()).toBe(6)
        expect(parsed.getDate()).toBe(16)
    })
})

describe('tomorrowLocalISODate', () => {
    it('rolls over to the first of the next month at a month boundary', () => {
        vi.setSystemTime(new Date('2026-07-31T10:00:00Z'))
        expect(tomorrowLocalISODate()).toBe('2026-08-01')
    })
})
