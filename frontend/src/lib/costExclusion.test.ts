import { describe, expect, it } from 'vitest'
import type { ExcludedSpan } from './api'
import { buildExclusionNotes, exclusionPhrase, formatSlotDuration } from './costExclusion'

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
        ['clamp_hidden_demand', null, 'demand may be hidden by EV or water'],
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
