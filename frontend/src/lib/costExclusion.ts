import type { ExcludedSpan } from './api'

/** Plain-language names of the components an exclusion reason can refer to. */
const COMPONENT_LABELS: Record<string, string> = {
    import: 'grid import',
    export: 'grid export',
    load: 'household load',
    water: 'water heater',
    ev: 'EV charger',
    battery_charge: 'battery charge',
    battery_discharge: 'battery discharge',
}

const FALLBACK_PHRASE = 'not compared'

function withComponent(component: string | null, suffix: string, bare: string): string {
    const label = component ? COMPONENT_LABELS[component] : undefined
    return label ? `${label} ${suffix}` : bare
}

/**
 * Fixed phrase for a backend reason code (and optional component). Raw codes are never
 * shown; an unknown future code falls back to "not compared".
 */
export function exclusionPhrase(reason: string, component: string | null = null): string {
    switch (reason) {
        case 'missing_slot':
            return 'not recorded'
        case 'ambiguous_rows':
            return 'duplicate records'
        case 'battery_cost_invalid':
            return 'battery wear cost invalid'
        case 'not_recorder':
            return 'backfilled data'
        case 'user_excluded':
            return 'excluded by you'
        case 'unsupported_provenance':
            return 'unsupported record format'
        case 'unconfigured_sensor':
            return withComponent(component, 'sensor not set up', 'sensor not set up')
        case 'estimated_component':
            return withComponent(component, 'estimated, not measured', 'estimated, not measured')
        case 'unknown_component':
            return withComponent(component, 'not measured', 'not measured')
        case 'battery_disabled_zero':
            return 'battery flow not recorded'
        case 'missing_price':
            return 'price missing'
        case 'missing_energy_value':
            return withComponent(component, 'reading missing', 'energy reading missing')
        case 'clamp_hidden_demand':
            return 'demand may be hidden by EV or water'
        case 'disabled_nonzero':
            return withComponent(component, 'reported energy while disabled', 'energy reported while disabled')
        default:
            return FALLBACK_PHRASE
    }
}

/** "2 h", "45 min" or "1 h 15 min" for a number of 15-minute slots. */
export function formatSlotDuration(slots: number): string {
    const minutes = Math.round(slots * 15)
    const hours = Math.floor(minutes / 60)
    const rest = minutes % 60
    if (hours === 0) return `${rest} min`
    return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`
}

export type ExclusionNotes = {
    /** At most two lines, largest group first, e.g. "2 h not compared: EV charger not measured" */
    lines: string[]
    /** Groups beyond the two shown, as "and N more reason(s)"; null when none */
    more: string | null
}

const MAX_GROUPS = 2

/** Reason notes for the coverage text; empty when nothing is excluded or no reason data. */
export function buildExclusionNotes(spans: readonly ExcludedSpan[] | undefined): ExclusionNotes {
    const slotsByPhrase = new Map<string, number>()
    for (const span of spans ?? []) {
        const phrase = exclusionPhrase(span.reason, span.component)
        slotsByPhrase.set(phrase, (slotsByPhrase.get(phrase) ?? 0) + span.slots)
    }
    // Array.prototype.sort is stable: equal groups keep chronological first-seen order.
    const groups = [...slotsByPhrase.entries()].sort((a, b) => b[1] - a[1])
    const lines = groups
        .slice(0, MAX_GROUPS)
        .map(([phrase, slots]) => `${formatSlotDuration(slots)} not compared: ${phrase}`)
    const rest = groups.length - MAX_GROUPS
    return { lines, more: rest > 0 ? `and ${rest} more ${rest === 1 ? 'reason' : 'reasons'}` : null }
}
