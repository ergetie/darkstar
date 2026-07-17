import { afterEach, describe, expect, it, vi } from 'vitest'
import { clampTo48hISO, filterSlotsByDay, formatHour, isTomorrow, isToday, isoToLocal, ymdLocal } from './time'

afterEach(() => {
    vi.useRealTimers()
})

describe('isToday / isTomorrow', () => {
    it('treats an instant just before UTC midnight as today when local (Stockholm) date has already rolled over', () => {
        // 2026-07-14T23:30:00Z is 2026-07-15T01:30 in Stockholm (summer, UTC+2)
        vi.setSystemTime(new Date('2026-07-14T23:30:00Z'))
        const now = new Date()
        expect(isToday('2026-07-15T00:00:00Z', now)).toBe(true)
        expect(isToday('2026-07-14T00:00:00Z', now)).toBe(false)
    })

    it('handles isTomorrow across a UTC-midnight boundary', () => {
        vi.setSystemTime(new Date('2026-07-14T23:30:00Z'))
        const now = new Date()
        // local tomorrow is 2026-07-16
        expect(isTomorrow('2026-07-16T10:00:00Z', now)).toBe(true)
        expect(isTomorrow('2026-07-15T10:00:00Z', now)).toBe(false)
    })

    it('handles isToday/isTomorrow across the Europe/Stockholm DST boundary (2026-10-25)', () => {
        // Sweden switches from CEST (UTC+2) to CET (UTC+1) at 2026-10-25T01:00:00Z
        vi.setSystemTime(new Date('2026-10-24T22:30:00Z')) // 2026-10-25T00:30 CEST
        const now = new Date()
        expect(isToday('2026-10-25T00:00:00Z', now)).toBe(true)
        expect(isTomorrow('2026-10-26T00:00:00Z', now)).toBe(true)

        vi.setSystemTime(new Date('2026-10-25T22:30:00Z')) // 2026-10-25T23:30 CET (post-DST)
        const nowAfter = new Date()
        expect(isToday('2026-10-25T20:00:00Z', nowAfter)).toBe(true)
        expect(isTomorrow('2026-10-26T20:00:00Z', nowAfter)).toBe(true)
    })
})

describe('filterSlotsByDay', () => {
    it('returns an empty array for an empty input list', () => {
        vi.setSystemTime(new Date('2026-07-15T10:00:00Z'))
        expect(filterSlotsByDay([], 'today', new Date())).toEqual([])
        expect(filterSlotsByDay([], 'tomorrow', new Date())).toEqual([])
    })

    it('filters slots to only those matching the selected day', () => {
        vi.setSystemTime(new Date('2026-07-15T10:00:00Z'))
        const now = new Date()
        const slots = [
            { start_time: '2026-07-15T00:00:00Z', label: 'today-1' },
            { start_time: '2026-07-15T12:00:00Z', label: 'today-2' },
            { start_time: '2026-07-16T12:00:00Z', label: 'tomorrow-1' },
        ]
        expect(filterSlotsByDay(slots, 'today', now).map((s) => s.label)).toEqual(['today-1', 'today-2'])
        expect(filterSlotsByDay(slots, 'tomorrow', now).map((s) => s.label)).toEqual(['tomorrow-1'])
    })
})

describe('clampTo48hISO', () => {
    it('returns an empty array when all instants are in the past', () => {
        const now = '2026-07-15T12:00:00Z'
        const isoList = ['2026-07-14T00:00:00Z', '2026-07-15T11:59:00Z']
        expect(clampTo48hISO(isoList, now)).toEqual([])
    })

    it('returns an empty array when all instants are beyond the 48h window', () => {
        const now = '2026-07-15T12:00:00Z'
        const isoList = ['2026-07-17T13:00:00Z', '2026-07-20T00:00:00Z']
        expect(clampTo48hISO(isoList, now)).toEqual([])
    })

    it('returns indices of instants within [now, now+48h)', () => {
        const now = '2026-07-15T12:00:00Z'
        const isoList = [
            '2026-07-14T00:00:00Z', // past -> excluded
            '2026-07-15T12:00:00Z', // exactly now -> included
            '2026-07-16T12:00:00Z', // within window -> included
            '2026-07-17T12:00:00Z', // exactly now+48h -> excluded (exclusive end)
        ]
        expect(clampTo48hISO(isoList, now)).toEqual([1, 2])
    })
})

describe('formatHour', () => {
    it('formats an ISO instant as a stable HH:mm string in Stockholm time', () => {
        expect(formatHour('2026-07-15T10:00:00Z')).toBe(formatHour('2026-07-15T10:00:00Z'))
        expect(formatHour('2026-07-15T10:00:00Z')).toMatch(/^\d{2}:\d{2}$/)
    })
})

describe('isoToLocal / ymdLocal', () => {
    it('round-trips an ISO string to a YYYY-MM-DD date in the given timezone', () => {
        const d = isoToLocal('2026-07-15T22:30:00Z')
        expect(ymdLocal(d)).toBe('2026-07-16')
    })
})
