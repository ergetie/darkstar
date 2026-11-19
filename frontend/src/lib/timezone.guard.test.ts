/// <reference types="vite/client" />
import { describe, expect, it } from 'vitest'

/**
 * Clocks and labels use the browser timezone and locale (`lib/timezone.ts`). A hardcoded
 * `Europe/Stockholm` or `sv-SE` would show Swedish time or formatting to every other viewer.
 *
 * Allowlist (documented):
 * - `./api.ts`: the doc comment naming the backend's default plan timezone.
 * Plan-timezone values come from `config.timezone` or `time_axis.timezone`, never a literal.
 */
const LITERAL = /Europe\/Stockholm|sv-SE/
const ALLOWLIST = ['./api.ts']

const SOURCES = import.meta.glob<string>(
    ['../**/*.{ts,tsx}', '!../**/*.test.{ts,tsx}', '!../test/**', '!../vite-env.d.ts'],
    { query: '?raw', import: 'default', eager: true },
)

function literals(source: string): string[] {
    return source
        .split('\n')
        .map((line, index) => ({ line, number: index + 1 }))
        .filter(({ line }) => LITERAL.test(line))
        .map(({ line, number }) => `${number}: ${line.trim()}`)
}

describe('timezone literal guard', () => {
    it('scans the frontend sources', () => {
        expect(Object.keys(SOURCES).length).toBeGreaterThan(50)
        expect(Object.keys(SOURCES)).toContain('./timezone.ts')
    })

    it('finds the literals it is meant to catch', () => {
        expect(literals("const tz = 'Europe/Stockholm'")).toHaveLength(1)
        expect(literals("d.toLocaleString('sv-SE')")).toHaveLength(1)
        expect(literals('const tz = displayTimeZone()')).toHaveLength(0)
    })

    it('has no hardcoded timezone or locale outside the allowlist', () => {
        const offenders = Object.entries(SOURCES)
            .filter(([file]) => !ALLOWLIST.includes(file))
            .flatMap(([file, source]) => literals(source).map((hit) => `${file}:${hit}`))
        expect(offenders).toEqual([])
    })
})
