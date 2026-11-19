import { afterEach, describe, expect, it, vi } from 'vitest'
import { displayLocale, displayTimeZone } from './timezone'

afterEach(() => {
    vi.restoreAllMocks()
})

describe('displayTimeZone', () => {
    it('returns the browser timezone', () => {
        vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
            timeZone: 'Pacific/Auckland',
        } as Intl.ResolvedDateTimeFormatOptions)
        expect(displayTimeZone()).toBe('Pacific/Auckland')
    })

    it('falls back to UTC when the timezone is empty', () => {
        vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockReturnValue({
            timeZone: '',
        } as Intl.ResolvedDateTimeFormatOptions)
        expect(displayTimeZone()).toBe('UTC')
    })

    it('falls back to UTC when resolution throws', () => {
        vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(() => {
            throw new Error('unsupported')
        })
        expect(displayTimeZone()).toBe('UTC')
    })
})

describe('displayLocale', () => {
    it('returns the browser language', () => {
        vi.spyOn(navigator, 'language', 'get').mockReturnValue('sv-SE')
        expect(displayLocale()).toBe('sv-SE')
    })

    it('falls back to en-US when the language is empty', () => {
        vi.spyOn(navigator, 'language', 'get').mockReturnValue('')
        expect(displayLocale()).toBe('en-US')
    })
})
