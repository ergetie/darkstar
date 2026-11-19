import { afterEach, describe, expect, it, vi } from 'vitest'
import * as timezone from '../lib/timezone'
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

describe('getDefaultDatesForPeriod near local midnight', () => {
    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('uses local calendar dates when the UTC date is the previous day', () => {
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Europe/Stockholm')
        // 00:30 Stockholm on 2026-07-15 is 2026-07-14T22:30Z
        const midnight = new Date('2026-07-14T22:30:00Z')
        expect(getDefaultDatesForPeriod('today', midnight)).toEqual({ start: '2026-07-14', end: '2026-07-15' })
        expect(getDefaultDatesForPeriod('yesterday', midnight)).toEqual({ start: '2026-07-14', end: '2026-07-14' })
        expect(getDefaultDatesForPeriod('week', midnight)).toEqual({ start: '2026-07-08', end: '2026-07-15' })
    })

    it('uses the browser day east of UTC at the end of the UTC day', () => {
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Pacific/Auckland')
        // 00:30 Auckland on 2026-07-16 is 2026-07-15T12:30Z
        const midnight = new Date('2026-07-15T12:30:00Z')
        expect(getDefaultDatesForPeriod('month', midnight)).toEqual({ start: '2026-06-16', end: '2026-07-16' })
    })

    it('crosses a DST change by calendar days, not 24 h steps', () => {
        vi.spyOn(timezone, 'displayTimeZone').mockReturnValue('Europe/Stockholm')
        // 2026-10-25 00:30 CEST; the day before has 25 h only after the change
        expect(getDefaultDatesForPeriod('week', new Date('2026-10-24T22:30:00Z'))).toEqual({
            start: '2026-10-18',
            end: '2026-10-25',
        })
        expect(getDefaultDatesForPeriod('today', new Date('2026-03-28T23:30:00Z'))).toEqual({
            start: '2026-03-28',
            end: '2026-03-29',
        })
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
