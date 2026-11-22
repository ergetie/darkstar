import { describe, expect, it } from 'vitest'
import type { ExcludedSpan } from './api'
import { buildExclusionNotes, buildPartialNotes, exclusionPhrase, formatSlotDuration } from './costExclusion'

function span(reason: string, slots: number, component: string | null = null): ExcludedSpan {
    return { start: '2026-10-05T08:00:00+02:00', end: '2026-10-05T09:00:00+02:00', slots, reason, component }
}

describe('exclusionPhrase', () => {
    it.each([
        ['missing_slot', null, 'not recorded'],
        ['ambiguous_rows', null, 'duplicate records'],
        ['battery_cost_invalid', null, 'battery wear cost invalid'],
        ['not_recorder', null, 'backfilled data'],
        ['user_excluded', null, 'excluded by you'],
        ['unsupported_provenance', null, 'unsupported record format'],
        ['unconfigured_sensor', 'ev', 'EV charger sensor not set up'],
        ['estimated_component', 'load', 'household load estimated, not measured'],
        ['unknown_component', 'ev', 'EV charger not measured'],
        ['unknown_component', 'water', 'water heater not measured'],
        ['unknown_component', 'battery_charge', 'battery charge not measured'],
        ['battery_disabled_zero', 'battery_charge', 'battery flow not recorded'],
        ['missing_price', null, 'price missing'],
        ['missing_energy_value', 'load', 'household load reading missing'],
        ['clamp_hidden_demand', null, 'demand may be understated'],
        ['disabled_nonzero', 'water', 'water heater reported energy while disabled'],
    ])('%s (%s) reads "%s"', (reason, component, expected) => {
        expect(exclusionPhrase(reason, component)).toBe(expected)
    })

    it('has component-less wording and never shows a raw code', () => {
        expect(exclusionPhrase('unknown_component', null)).toBe('not measured')
        expect(exclusionPhrase('unknown_component', 'something_new')).toBe('not measured')
        expect(exclusionPhrase('missing_energy_value')).toBe('energy reading missing')
    })

    it('falls back to "not compared" for an unknown future code', () => {
        expect(exclusionPhrase('brand_new_code', 'ev')).toBe('not compared')
    })
})

describe('formatSlotDuration', () => {
    it.each([
        [1, '15 min'],
        [3, '45 min'],
        [4, '1 h'],
        [5, '1 h 15 min'],
        [8, '2 h'],
        [16, '4 h'],
    ])('%i slots is %s', (slots, expected) => {
        expect(formatSlotDuration(slots)).toBe(expected)
    })
})

describe('buildExclusionNotes', () => {
    it('is empty without spans or reason data', () => {
        expect(buildExclusionNotes(undefined)).toEqual({ lines: [], more: null })
        expect(buildExclusionNotes([])).toEqual({ lines: [], more: null })
    })

    it('names a single reason', () => {
        expect(buildExclusionNotes([span('unknown_component', 8, 'ev')])).toEqual({
            lines: ['2 h not compared: EV charger not measured'],
            more: null,
        })
    })

    it('merges spans with the same wording and orders largest first', () => {
        const notes = buildExclusionNotes([
            span('missing_price', 4),
            span('unknown_component', 4, 'ev'),
            span('unknown_component', 8, 'ev'),
        ])
        expect(notes.lines).toEqual(['3 h not compared: EV charger not measured', '1 h not compared: price missing'])
        expect(notes.more).toBeNull()
    })

    it('lists the two largest of several reasons and counts the rest', () => {
        const notes = buildExclusionNotes([
            span('missing_slot', 2),
            span('unknown_component', 8, 'ev'),
            span('missing_price', 4),
            span('user_excluded', 1),
        ])
        expect(notes.lines).toEqual(['2 h not compared: EV charger not measured', '1 h not compared: price missing'])
        expect(notes.more).toBe('and 2 more reasons')
    })

    it('uses the singular for one remaining reason', () => {
        const notes = buildExclusionNotes([span('a', 3), span('missing_price', 2), span('missing_slot', 1)])
        expect(notes.more).toBe('and 1 more reason')
    })

    it('breaks ties by first appearance', () => {
        const notes = buildExclusionNotes([span('missing_price', 4), span('missing_slot', 4)])
        expect(notes.lines[0]).toContain('price missing')
    })
})

describe('buildPartialNotes', () => {
    const tz = 'Europe/Stockholm'
    const ev = (start: string, end: string, slots: number, reason = 'unmeasured_component'): ExcludedSpan => ({
        start,
        end,
        slots,
        reason,
        component: 'ev',
    })

    it('is empty without spans', () => {
        expect(buildPartialNotes(undefined, tz)).toEqual({ lines: [], more: null })
        expect(buildPartialNotes([], tz)).toEqual({ lines: [], more: null })
    })

    it('names the EV gap with duration and time range', () => {
        const notes = buildPartialNotes([ev('2026-11-09T10:00:00+01:00', '2026-11-10T12:15:00+01:00', 105)], tz)
        expect(notes.lines).toEqual(['EV not measured for 26 h 15 min (Nov 9 10:00-Nov 10 12:15)'])
        expect(notes.more).toBeNull()
    })

    it('shows one line per component and uses the longest span range', () => {
        const notes = buildPartialNotes(
            [
                ev('2026-11-09T10:00:00+01:00', '2026-11-09T11:00:00+01:00', 4),
                { ...ev('2026-11-09T12:00:00+01:00', '2026-11-09T14:00:00+01:00', 8), component: 'water' },
                ev('2026-11-09T15:00:00+01:00', '2026-11-09T18:00:00+01:00', 12),
            ],
            tz,
        )
        expect(notes.lines).toEqual([
            'EV not measured for 4 h (Nov 9 15:00-Nov 9 18:00)',
            'Water heater not measured for 2 h (Nov 9 12:00-Nov 9 14:00)',
        ])
    })

    it('caps at two lines, words unconfigured sensors and falls back for unknown devices', () => {
        const base = { start: '2026-11-09T10:00:00+01:00', end: '2026-11-09T11:00:00+01:00' }
        const notes = buildPartialNotes(
            [
                { ...base, slots: 8, reason: 'unmeasured_component', component: 'ev' },
                { ...base, slots: 6, reason: 'unconfigured_sensor', component: 'water' },
                { ...base, slots: 4, reason: 'unmeasured_component', component: 'heatpump' },
            ],
            tz,
        )
        expect(notes.lines[1]).toContain('Water heater sensor not set up for 1 h 30 min')
        expect(notes.more).toBe('and 1 more')
        expect(
            buildPartialNotes([{ ...base, slots: 4, reason: 'unmeasured_component', component: null }], tz).lines[0],
        ).toContain('Device not measured for 1 h')
    })
})
