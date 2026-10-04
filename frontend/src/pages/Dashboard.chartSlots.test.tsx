import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import type { ScheduleSlot } from '../lib/types'
import { useChartSlots } from './Dashboard'

// Hourly slots over three Stockholm days (CEST, UTC+2): 2026-10-04 .. 2026-10-06.
const schedule: ScheduleSlot[] = Array.from({ length: 72 }, (_, i) => ({
    start_time: new Date(Date.UTC(2026, 9, 3, 22 + i)).toISOString(),
})) as ScheduleSlot[]

const dayOf = (slot: ScheduleSlot) =>
    new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Stockholm' }).format(new Date(slot.start_time))

describe('useChartSlots', () => {
    beforeEach(() => {
        vi.useFakeTimers()
        // 23:50 local on 2026-10-04
        vi.setSystemTime(new Date('2026-10-04T21:50:00Z'))
    })
    afterEach(() => {
        vi.useRealTimers()
    })

    it('keeps the same array within a day and recomputes after midnight', () => {
        const { result, rerender } = renderHook(() => useChartSlots(schedule, null))
        const first = result.current
        expect(new Set(first?.map(dayOf))).toEqual(new Set(['2026-10-04', '2026-10-05']))

        // Live metric re-render on the same day: identical array
        vi.setSystemTime(new Date('2026-10-04T21:59:00Z'))
        rerender()
        expect(result.current).toBe(first)

        // Re-render after local midnight: new day split
        vi.setSystemTime(new Date('2026-10-04T22:01:00Z'))
        rerender()
        expect(result.current).not.toBe(first)
        expect(new Set(result.current?.map(dayOf))).toEqual(new Set(['2026-10-05', '2026-10-06']))

        const second = result.current
        rerender()
        expect(result.current).toBe(second)
    })
})
