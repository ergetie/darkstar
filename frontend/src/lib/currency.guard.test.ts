/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest'

/**
 * The configured currency is the only source of currency text. A literal currency code or
 * subunit name in a UI source would show the wrong unit once `nordpool.currency` is not SEK.
 * `lib/currency.ts` holds the subunit table and is the only allowlisted source.
 */
const LITERAL = /\bSEK\b|öre|\bkr\b/
const ALLOWLIST = ['./currency.ts']

const SOURCES = import.meta.glob<string>(
    ['../**/*.{ts,tsx,css}', '!../**/*.test.{ts,tsx}', '!../test/**', '!../vite-env.d.ts'],
    { query: '?raw', import: 'default', eager: true },
)

function currencyLiterals(source: string): string[] {
    return source
        .split('\n')
        .map((line, index) => ({ line, number: index + 1 }))
        .filter(({ line }) => LITERAL.test(line))
        .map(({ line, number }) => `${number}: ${line.trim()}`)
}

describe('currency literal guard', () => {
    it('scans the frontend sources', () => {
        expect(Object.keys(SOURCES).length).toBeGreaterThan(50)
        expect(Object.keys(SOURCES)).toContain('./currency.ts')
    })

    it('finds the literals it is meant to catch', () => {
        expect(currencyLiterals('const a = "1.2 SEK/kWh"')).toHaveLength(1)
        expect(currencyLiterals('price + " öre"')).toHaveLength(1)
        expect(currencyLiterals('`${x} kr`')).toHaveLength(1)
        expect(currencyLiterals('const sekPerKwh = 1; // _sek keys and Kroner')).toHaveLength(0)
    })

    it('has no currency literal outside the allowlist', () => {
        const offenders = Object.entries(SOURCES)
            .filter(([file]) => !ALLOWLIST.includes(file))
            .flatMap(([file, source]) => currencyLiterals(source).map((hit) => `${file}:${hit}`))
        expect(offenders).toEqual([])
    })
})
