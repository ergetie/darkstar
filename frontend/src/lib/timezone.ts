/**
 * Display timezone and locale: the viewer's browser, never a hardcoded zone.
 *
 * Plan timezone (`config.timezone`, `time_axis.timezone`) is a separate concept kept only for
 * backend-defined semantics (tariff windows, cost buckets). Everything the user reads on a clock
 * uses these helpers. Exported as functions so tests can mock them.
 */

const FALLBACK_TIME_ZONE = 'UTC'
const FALLBACK_LOCALE = 'en-US'

/** IANA timezone of the browser, `UTC` when it cannot be resolved. */
export function displayTimeZone(): string {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || FALLBACK_TIME_ZONE
    } catch {
        return FALLBACK_TIME_ZONE
    }
}

/** BCP 47 locale of the browser for number and text formatting. */
export function displayLocale(): string {
    if (typeof navigator === 'undefined') return FALLBACK_LOCALE
    return navigator.language || FALLBACK_LOCALE
}
