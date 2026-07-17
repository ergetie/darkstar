import { describe, expect, it } from 'vitest'
import { getDefaultDatesForPeriod, isValidDateRange } from './CommandDomains'

const now = new Date('2026-07-15T12:00:00Z')

describe('getDefaultDatesForPeriod', () => {
    it('today -> yesterday through today', () => {
        expect(getDefaultDatesForPeriod('today', now)).toEqual({ start: '2026-07-14', end: '2026-07-15' })
    })

    it('yesterday -> a single day (yesterday only)', () => {
        expect(getDefaultDatesForPeriod('yesterday', now)).toEqual({ start: '2026-07-14', end: '2026-07-14' })
    })

    it('week -> 7 days ago through today', () => {
        expect(getDefaultDatesForPeriod('week', now)).toEqual({ start: '2026-07-08', end: '2026-07-15' })
    })

    it('month -> 30 days ago through today', () => {
        expect(getDefaultDatesForPeriod('month', now)).toEqual({ start: '2026-06-15', end: '2026-07-15' })
    })

    it('custom -> defaults to the last 7 days', () => {
        expect(getDefaultDatesForPeriod('custom', now)).toEqual({ start: '2026-07-08', end: '2026-07-15' })
    })
})

describe('isValidDateRange', () => {
    it('is invalid when end is before start', () => {
        expect(isValidDateRange('2026-07-15', '2026-07-14')).toBe(false)
    })

    it('is valid when start equals end', () => {
        expect(isValidDateRange('2026-07-15', '2026-07-15')).toBe(true)
    })

    it('is invalid when either date is an empty string', () => {
        expect(isValidDateRange('', '2026-07-15')).toBe(false)
        expect(isValidDateRange('2026-07-15', '')).toBe(false)
        expect(isValidDateRange('', '')).toBe(false)
    })
})
