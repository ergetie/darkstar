/**
 * Design-token colours for canvas drawing. Tokens are space-separated RGB triplets
 * (`--color-good: 31 178 86`), so Chart.js (which cannot read CSS vars) gets them
 * resolved at draw time. Re-resolved whenever the root class list changes, so the
 * light/dark switch repaints with the right colours on the next draw.
 */
export type ChartToken =
    | 'accent'
    | 'good'
    | 'bad'
    | 'warn'
    | 'water'
    | 'house'
    | 'grid'
    | 'peak'
    | 'night'
    | 'ai'
    | 'text'
    | 'muted'
    | 'line'
    | 'surface'
    | 'canvas'

/** Neutral grey used only when the stylesheet is unavailable (tests, SSR). */
const FALLBACK_TRIPLET = '128, 128, 128'

let cacheKey: string | null = null
const cache = new Map<ChartToken, string>()

function themeKey(): string {
    return typeof document === 'undefined' ? '' : document.documentElement.className
}

/** "31 178 86" -> "31, 178, 86"; null when the value is not an RGB triplet. */
export function parseTriplet(raw: string): string | null {
    const parts = raw
        .trim()
        .split(/[\s,]+/)
        .filter(Boolean)
    if (parts.length !== 3) return null
    if (parts.some((p) => !Number.isFinite(Number(p)))) return null
    return parts.map((p) => String(Math.round(Number(p)))).join(', ')
}

function triplet(name: ChartToken): string {
    const key = themeKey()
    if (key !== cacheKey) {
        cache.clear()
        cacheKey = key
    }
    const hit = cache.get(name)
    if (hit) return hit
    let resolved: string | null = null
    if (typeof document !== 'undefined' && typeof getComputedStyle === 'function') {
        resolved = parseTriplet(getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`))
    }
    if (resolved) cache.set(name, resolved)
    return resolved ?? FALLBACK_TRIPLET
}

/** CSS colour string for a design token at the given opacity (0..1). */
export function token(name: ChartToken, alpha = 1): string {
    return `rgba(${triplet(name)}, ${alpha})`
}

/** True while the root carries the `.dark` class (glows and grid strength depend on it). */
export function isDarkTheme(): boolean {
    return typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
}

/**
 * Opacity of the `line` token for chart grid lines. The light-theme line token is darker
 * relative to its surface than the dark one is, so light needs less opacity to stay subtle.
 * Hour lines are always fainter than the 25 % SoC lines.
 */
export function gridAlpha(kind: 'hour' | 'soc', dark: boolean): number {
    if (kind === 'hour') return dark ? 0.3 : 0.14
    return dark ? 0.55 : 0.3
}
