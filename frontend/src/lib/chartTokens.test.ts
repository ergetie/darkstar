import { describe, expect, it } from 'vitest'
import { gridAlpha, isDarkTheme, parseTriplet, token } from './chartTokens'

describe('chartTokens', () => {
    it('parses space-separated RGB triplets', () => {
        expect(parseTriplet('31 178 86')).toBe('31, 178, 86')
        expect(parseTriplet(' 31  178 86 ')).toBe('31, 178, 86')
    })

    it('rejects anything that is not three numbers', () => {
        expect(parseTriplet('')).toBeNull()
        expect(parseTriplet('31 178')).toBeNull()
        expect(parseTriplet('red green blue')).toBeNull()
    })

    it('always returns a usable rgba string, even without a stylesheet', () => {
        expect(token('good', 0.5)).toMatch(/^rgba\(\d+, \d+, \d+, 0\.5\)$/)
    })

    it('follows the .dark class on the root', () => {
        document.documentElement.classList.remove('dark')
        expect(isDarkTheme()).toBe(false)
        document.documentElement.classList.add('dark')
        expect(isDarkTheme()).toBe(true)
        document.documentElement.classList.remove('dark')
    })

    it('keeps hour lines subtler than SoC lines in both themes', () => {
        for (const dark of [true, false]) {
            expect(gridAlpha('hour', dark)).toBeLessThan(gridAlpha('soc', dark))
            expect(gridAlpha('soc', dark)).toBeLessThanOrEqual(0.6)
        }
    })
})
