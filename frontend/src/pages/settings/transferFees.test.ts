import { describe, expect, it } from 'vitest'
import vectors from '../../../../tests/fixtures/time_window_vectors.json'
import {
    matchesWindow,
    parseLocalDateTime,
    resolveTransferFee,
    rulesError,
    swedishPublicHolidays,
    validateWindow,
    type TransferFeeRule,
} from './transferFees'

describe('shared time-window vectors (kept in sync with pytest)', () => {
    it.each(vectors.map((v) => [v.name, v] as const))('%s', (_name, v) => {
        validateWindow(v.window)
        const dt = parseLocalDateTime(v.local_datetime)
        expect(matchesWindow(v.window as Omit<TransferFeeRule, 'fee_sek'>, dt, v.holidays_as_weekend)).toBe(v.expected)
    })
})

describe('swedishPublicHolidays', () => {
    it('computes the 2027 moving holidays from the spec', () => {
        const h = swedishPublicHolidays(2027)
        expect(h.has('2027-03-26')).toBe(true)
        expect(h.has('2027-03-29')).toBe(true)
        expect(h.has('2027-06-26')).toBe(true)
        expect(h.has('2027-06-25')).toBe(true)
        expect(h.size).toBe(16)
    })

    it('computes 2026 Alla helgons dag and Kristi himmelsfärd', () => {
        const h = swedishPublicHolidays(2026)
        expect(h.has('2026-10-31')).toBe(true)
        expect(h.has('2026-05-14')).toBe(true)
    })
})

describe('rulesError', () => {
    it('names the offending rule', () => {
        expect(rulesError([{ fee_sek: 0.1 }, { hours: { start: 8, end: 8 }, fee_sek: 0.1 }])).toMatch(/^Rule 2:/)
        expect(rulesError([{ months: [13], fee_sek: 0.1 }])).toMatch(/months/)
        expect(rulesError([{ fee_sek: -1 }])).toMatch(/negative/)
        expect(rulesError([{ fee_sek: 0.3, weekdays: [0, 6] }])).toBeNull()
    })
})

describe('resolveTransferFee', () => {
    const rules: TransferFeeRule[] = [
        { hours: { start: 8, end: 8 }, fee_sek: 9 },
        { months: [12], weekdays: [0, 1, 2, 3, 4], hours: { start: 6, end: 22 }, fee_sek: 0.76 },
        { fee_sek: 0.5 },
    ]
    const at = (s: string) => parseLocalDateTime(s)

    it('uses the flat fee in flat mode', () => {
        expect(resolveTransferFee('flat', rules, 0.25, at('2026-12-01T10:00'), false).fee).toBe(0.25)
    })

    it('skips invalid rules and uses first match', () => {
        expect(resolveTransferFee('time_of_use', rules, 0.25, at('2026-12-01T10:00'), false)).toEqual({
            fee: 0.76,
            ruleIndex: 1,
        })
        expect(resolveTransferFee('time_of_use', rules, 0.25, at('2026-12-01T23:00'), false).ruleIndex).toBe(2)
        expect(resolveTransferFee('time_of_use', rules.slice(0, 2), 0.25, at('2026-12-01T23:00'), false)).toEqual({
            fee: 0.25,
            ruleIndex: null,
        })
    })
})
