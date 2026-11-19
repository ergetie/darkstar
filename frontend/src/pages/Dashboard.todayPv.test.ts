import { afterEach, describe, expect, it, vi } from 'vitest'
import * as timezone from '../lib/timezone'
import { todayPvForecastKwh } from './Dashboard'

afterEach(() => {
    vi.restoreAllMocks()
})

const slot = (slot_start: string, pv_kwh: number) => ({ slot_start, final: { pv_kwh } })

describe('todayPvForecastKwh', () => {
    it('uses the local date at 00:30 local when the UTC date is still the previous day', () => {
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Europe/Stockholm')
        // 00:30 Stockholm on 2026-07-15 is 2026-07-14T22:30Z
        const now = new Date('2026-07-14T22:30:00Z')
        const slots = [
            slot('2026-07-14T21:45:00Z', 1), // 23:45 on the 14th local: yesterday
            slot('2026-07-14T22:00:00Z', 2), // 00:00 on the 15th local: today
            slot('2026-07-15T08:00:00+02:00', 3),
            slot('2026-07-15T22:00:00Z', 4), // 00:00 on the 16th local: tomorrow
        ]
        expect(todayPvForecastKwh(slots, now)).toBe(5)
    })

    it('uses the browser day for slots serialized in another timezone', () => {
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Pacific/Auckland')
        // 00:30 Auckland on 2026-07-16 (UTC+12) is 2026-07-15T12:30Z
        const now = new Date('2026-07-15T12:30:00Z')
        const slots = [
            slot('2026-07-15T13:00:00+02:00', 1), // 23:00 on the 15th Auckland: yesterday
            slot('2026-07-15T14:00:00+02:00', 2), // 00:00 on the 16th Auckland: today
        ]
        expect(todayPvForecastKwh(slots, now)).toBe(2)
    })
})
